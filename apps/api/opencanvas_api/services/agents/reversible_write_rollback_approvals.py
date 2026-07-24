"""Server-authoritative issuance of one immutable reversible-write rollback approval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    ControlledAgentCapabilityGrant,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteRollbackApproval,
    ControlledAgentReversibleWriteRollbackEvidence,
)
from opencanvas_api.services.agents.reversible_write_rollback_review import (
    ReversibleWriteRollbackReviewService,
)
from opencanvas_api.services.agents.reversible_writes import (
    ROLLBACK_APPROVAL_TTL,
    ReversibleWriteAction,
    ReversibleWriteRollbackAction,
    RollbackApprovalDigestInput,
    authoritative_absence_digest,
    rollback_approval_digest,
)


class RollbackApprovalError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class IssuedRollbackApproval:
    approval: ControlledAgentReversibleWriteRollbackApproval
    duplicate: bool


class ReversibleWriteRollbackApprovalService:
    """Issues approval only; it never applies the compensating note operation."""

    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self.session = session
        self.now = now or datetime.now(UTC)

    async def issue(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        effect_id: uuid.UUID,
        idempotency_key: str,
    ) -> IssuedRollbackApproval:
        async with self.session.begin_nested():
            review = await ReversibleWriteRollbackReviewService(self.session, now=self.now).review(
                authenticated_user_id=authenticated_user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                effect_id=effect_id,
            )
            if not review.eligible:
                raise RollbackApprovalError(
                    review.denial_reason or "approval_invalid", "Rollback is not eligible."
                )
            effect = await self.session.get(ControlledAgentReversibleWriteEffect, effect_id)
            if effect is None or review.note_id is None or review.rollback_action is None:
                raise RollbackApprovalError(
                    "approval_invalid", "Rollback authority is unavailable."
                )
            grant = await self.session.scalar(
                select(ControlledAgentCapabilityGrant).where(
                    ControlledAgentCapabilityGrant.execution_id == effect.execution_id,
                    ControlledAgentCapabilityGrant.user_id == authenticated_user_id,
                    ControlledAgentCapabilityGrant.workspace_id == workspace_id,
                )
            )
            if grant is None:
                raise RollbackApprovalError(
                    "capability_missing", "Rollback capability is unavailable."
                )
            action = ReversibleWriteRollbackAction(review.rollback_action)
            evidence: ControlledAgentReversibleWriteRollbackEvidence | None = None
            target_digest = authoritative_absence_digest()
            if effect.action == ReversibleWriteAction.NOTE_UPDATE.value:
                evidence = await self.session.scalar(
                    select(ControlledAgentReversibleWriteRollbackEvidence).where(
                        ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect.effect_id
                    )
                )
                if evidence is None:
                    raise RollbackApprovalError(
                        "rollback_evidence_missing", "Rollback evidence is unavailable."
                    )
                target_digest = evidence.before_digest
            existing = await self.session.scalar(
                select(ControlledAgentReversibleWriteRollbackApproval).where(
                    ControlledAgentReversibleWriteRollbackApproval.execution_id
                    == effect.execution_id,
                    ControlledAgentReversibleWriteRollbackApproval.user_id == authenticated_user_id,
                    ControlledAgentReversibleWriteRollbackApproval.workspace_id == workspace_id,
                    ControlledAgentReversibleWriteRollbackApproval.canvas_id == canvas_id,
                    ControlledAgentReversibleWriteRollbackApproval.scoped_idempotency_key
                    == idempotency_key,
                )
            )
            expires_at = (
                existing.expires_at if existing is not None else self.now + ROLLBACK_APPROVAL_TTL
            )
            digest_input = RollbackApprovalDigestInput(
                execution_id=effect.execution_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                note_id=effect.resulting_resource_id,
                proposal_id=effect.proposal_id,
                effect_id=effect.effect_id,
                forward_action=ReversibleWriteAction(effect.action),
                rollback_action=action,
                original_plan_digest=effect.plan_digest,
                expected_current_revision=effect.resulting_revision,
                effect_after_state_digest=effect.after_digest,
                rollback_target_kind=review.rollback_target_kind or "",
                rollback_target_digest=target_digest,
                rollback_evidence_id=evidence.evidence_id if evidence else None,
                grant_id=grant.grant_id,
                scoped_idempotency_key=idempotency_key,
                expires_at=expires_at,
            )
            if existing is not None:
                if self._same(existing, digest_input):
                    return IssuedRollbackApproval(existing, True)
                raise RollbackApprovalError(
                    "idempotency_conflict", "Rollback idempotency key is already bound."
                )
            approval = ControlledAgentReversibleWriteRollbackApproval(
                rollback_approval_id=uuid.uuid4(),
                execution_id=digest_input.execution_id,
                user_id=digest_input.user_id,
                workspace_id=digest_input.workspace_id,
                canvas_id=digest_input.canvas_id,
                note_id=digest_input.note_id,
                proposal_id=digest_input.proposal_id,
                effect_id=digest_input.effect_id,
                forward_action=digest_input.forward_action.value,
                rollback_action=digest_input.rollback_action.value,
                rollback_evidence_id=digest_input.rollback_evidence_id,
                original_plan_digest=digest_input.original_plan_digest,
                expected_current_revision=digest_input.expected_current_revision,
                effect_after_state_digest=digest_input.effect_after_state_digest,
                rollback_target_kind=digest_input.rollback_target_kind,
                rollback_target_digest=digest_input.rollback_target_digest,
                grant_id=digest_input.grant_id,
                scoped_idempotency_key=idempotency_key,
                approval_digest=rollback_approval_digest(digest_input),
                created_at=self.now,
                expires_at=expires_at,
            )
            self.session.add(approval)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise RollbackApprovalError(
                    "idempotency_conflict", "Rollback approval already exists."
                ) from exc
            return IssuedRollbackApproval(approval, False)

    @staticmethod
    def _same(
        approval: ControlledAgentReversibleWriteRollbackApproval,
        value: RollbackApprovalDigestInput,
    ) -> bool:
        return (
            approval.proposal_id == value.proposal_id
            and approval.effect_id == value.effect_id
            and approval.note_id == value.note_id
            and approval.forward_action == value.forward_action.value
            and approval.rollback_action == value.rollback_action.value
            and approval.original_plan_digest == value.original_plan_digest
            and approval.expected_current_revision == value.expected_current_revision
            and approval.effect_after_state_digest == value.effect_after_state_digest
            and approval.rollback_target_kind == value.rollback_target_kind
            and approval.rollback_target_digest == value.rollback_target_digest
            and approval.rollback_evidence_id == value.rollback_evidence_id
            and approval.grant_id == value.grant_id
            and approval.approval_digest == rollback_approval_digest(value)
        )
