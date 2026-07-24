"""Atomic, server-authoritative execution of one approved note rollback."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    Canvas,
    CanvasNode,
    ControlledAgentCapabilityGrant,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteRollbackApproval,
    ControlledAgentReversibleWriteRollbackEvidence,
    ControlledAgentReversibleWriteRollbackResult,
)
from opencanvas_api.services.agents.contracts import AuditAttribute, AuditEvent
from opencanvas_api.services.agents.persistence import ControlledAgentRepository
from opencanvas_api.services.agents.reversible_write_effects import (
    _note_digest,
    _note_state,
    _note_state_digest,
)
from opencanvas_api.services.agents.reversible_write_rollback_review import (
    ReversibleWriteRollbackReviewService,
)
from opencanvas_api.services.agents.reversible_writes import (
    ReversibleWriteAction,
    ReversibleWriteRollbackAction,
    RollbackApprovalDigestInput,
    authoritative_absence_digest,
    rollback_approval_digest,
)
from opencanvas_api.services.trace import CompleteTraceInput, StartTraceInput, TraceService

FailureHook = Callable[[], Awaitable[None]]


class RollbackExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class AppliedRollback:
    result: ControlledAgentReversibleWriteRollbackResult
    duplicate: bool


class ReversibleWriteRollbackService:
    """Apply one exact inverse note mutation and its evidence atomically."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        after_mutation: FailureHook | None = None,
        after_result: FailureHook | None = None,
        after_audit: FailureHook | None = None,
    ) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)
        self.now = now or datetime.now(UTC)
        self.after_mutation = after_mutation
        self.after_result = after_result
        self.after_audit = after_audit

    async def apply(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        effect_id: uuid.UUID,
        rollback_approval_id: uuid.UUID,
        idempotency_key: str,
    ) -> AppliedRollback:
        existing = await self.session.scalar(
            select(ControlledAgentReversibleWriteRollbackResult).where(
                ControlledAgentReversibleWriteRollbackResult.user_id
                == authenticated_user_id,
                ControlledAgentReversibleWriteRollbackResult.workspace_id == workspace_id,
                ControlledAgentReversibleWriteRollbackResult.canvas_id == canvas_id,
                ControlledAgentReversibleWriteRollbackResult.scoped_idempotency_key
                == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.rollback_approval_id == rollback_approval_id
                and existing.effect_id == effect_id
            ):
                return AppliedRollback(existing, True)
            raise RollbackExecutionError(
                "idempotency_conflict", "Rollback request conflicts."
            )
        completed = await self.session.scalar(
            select(ControlledAgentReversibleWriteRollbackResult).where(
                ControlledAgentReversibleWriteRollbackResult.effect_id == effect_id,
                ControlledAgentReversibleWriteRollbackResult.user_id
                == authenticated_user_id,
                ControlledAgentReversibleWriteRollbackResult.workspace_id == workspace_id,
                ControlledAgentReversibleWriteRollbackResult.canvas_id == canvas_id,
            )
        )
        if completed is not None:
            raise RollbackExecutionError(
                "already_rolled_back", "Rollback was already completed."
            )

        async with self.session.begin_nested():
            approval = await self.session.scalar(
                select(ControlledAgentReversibleWriteRollbackApproval).where(
                    ControlledAgentReversibleWriteRollbackApproval.rollback_approval_id
                    == rollback_approval_id,
                    ControlledAgentReversibleWriteRollbackApproval.effect_id == effect_id,
                    ControlledAgentReversibleWriteRollbackApproval.user_id
                    == authenticated_user_id,
                    ControlledAgentReversibleWriteRollbackApproval.workspace_id == workspace_id,
                    ControlledAgentReversibleWriteRollbackApproval.canvas_id == canvas_id,
                )
            )
            if approval is None:
                raise RollbackExecutionError(
                    "approval_not_found", "Rollback approval not found.", 404
                )
            expires_at = self._aware(approval.expires_at)
            if self.now >= expires_at:
                raise RollbackExecutionError(
                    "approval_expired", "Rollback approval has expired."
                )
            review = await ReversibleWriteRollbackReviewService(
                self.session, now=self.now
            ).review(
                authenticated_user_id=authenticated_user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                effect_id=effect_id,
            )
            if not review.eligible:
                raise RollbackExecutionError(
                    review.denial_reason or "rollback_invalid",
                    "Rollback is not eligible.",
                )
            effect = await self.session.get(ControlledAgentReversibleWriteEffect, effect_id)
            if effect is None:
                raise RollbackExecutionError(
                    "effect_not_found", "Rollback effect not found.", 404
                )
            evidence = await self.session.scalar(
                select(ControlledAgentReversibleWriteRollbackEvidence).where(
                    ControlledAgentReversibleWriteRollbackEvidence.effect_id == effect_id
                )
            )
            grant = await self.session.scalar(
                select(ControlledAgentCapabilityGrant).where(
                    ControlledAgentCapabilityGrant.grant_id == approval.grant_id,
                    ControlledAgentCapabilityGrant.execution_id == effect.execution_id,
                    ControlledAgentCapabilityGrant.user_id == authenticated_user_id,
                    ControlledAgentCapabilityGrant.workspace_id == workspace_id,
                )
            )
            if grant is None:
                raise RollbackExecutionError(
                    "grant_scope_mismatch", "Rollback authority is unavailable."
                )
            digest_input = self._approval_digest_input(
                approval=approval,
                effect=effect,
                evidence=evidence,
                expires_at=expires_at,
            )
            if not self._approval_matches(approval, digest_input):
                raise RollbackExecutionError(
                    "approval_invalid", "Rollback approval is invalid."
                )
            note = await self.session.scalar(
                select(CanvasNode).where(
                    CanvasNode.id == approval.note_id,
                    CanvasNode.canvas_id == canvas_id,
                    CanvasNode.type == "note",
                )
            )
            if note is None:
                raise RollbackExecutionError(
                    "note_missing", "Rollback target is unavailable."
                )
            trace_id = uuid.uuid4()
            trace = TraceService(self.session)
            await trace.start_trace(
                StartTraceInput(
                    trace_id=trace_id,
                    parent_trace_id=effect.trace_id,
                    event_type="reversible_write.rollback",
                    actor_id=str(authenticated_user_id),
                    actor_type="user",
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    object_id=note.id,
                    object_type="canvas_node",
                    operation=f"reversible_write.{approval.rollback_action}",
                    metadata={
                        "effectId": str(effect.effect_id),
                        "rollbackApprovalId": str(approval.rollback_approval_id),
                    },
                )
            )
            resulting_revision, target_digest = await self._apply_inverse(
                approval=approval,
                effect=effect,
                evidence=evidence,
                note=note,
            )
            if self.after_mutation is not None:
                await self.after_mutation()
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
                scoped_idempotency_key=idempotency_key,
                expected_pre_rollback_revision=approval.expected_current_revision,
                resulting_revision=resulting_revision,
                pre_rollback_state_digest=effect.after_digest,
                post_rollback_target_digest=target_digest,
                trace_id=trace_id,
                created_at=self.now,
            )
            self.session.add(result)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise RollbackExecutionError(
                    "idempotency_conflict", "Rollback result already exists."
                ) from exc
            if self.after_result is not None:
                await self.after_result()
            await self.repository.append_audit_event(
                AuditEvent(
                    event_id=uuid.uuid4(),
                    trace_id=trace_id,
                    execution_id=effect.execution_id,
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    event_type="reversible_write.rollback_applied",
                    recorded_at=self.now,
                    attributes=(
                        AuditAttribute(
                            key="rollback_action", value=approval.rollback_action
                        ),
                        AuditAttribute(
                            key="rollback_approval_digest",
                            value=approval.approval_digest,
                        ),
                        AuditAttribute(key="effect_id", value=str(effect.effect_id)),
                        AuditAttribute(
                            key="pre_rollback_digest", value=effect.after_digest
                        ),
                        AuditAttribute(key="target_digest", value=target_digest),
                        AuditAttribute(
                            key="resulting_revision", value=resulting_revision
                        ),
                    ),
                )
            )
            if self.after_audit is not None:
                await self.after_audit()
            await trace.complete_trace(
                CompleteTraceInput(
                    trace_id=trace_id,
                    parent_trace_id=effect.trace_id,
                    event_type="reversible_write.rollback",
                    actor_id=str(authenticated_user_id),
                    actor_type="user",
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    object_id=approval.note_id,
                    object_type="canvas_node",
                    operation=f"reversible_write.{approval.rollback_action}",
                    metadata={
                        "rollbackResultId": str(result.rollback_result_id),
                        "resultingRevision": resulting_revision,
                    },
                )
            )
            await self.session.flush()
        return AppliedRollback(result, False)

    async def _apply_inverse(
        self,
        *,
        approval: ControlledAgentReversibleWriteRollbackApproval,
        effect: ControlledAgentReversibleWriteEffect,
        evidence: ControlledAgentReversibleWriteRollbackEvidence | None,
        note: CanvasNode,
    ) -> tuple[int | None, str]:
        if approval.rollback_action == ReversibleWriteRollbackAction.NOTE_CREATE_ROLLBACK.value:
            if (
                approval.expected_current_revision != 0
                or approval.rollback_target_kind != "authoritative_absence"
                or approval.rollback_target_digest != authoritative_absence_digest()
                or _note_digest(note) != effect.after_digest
            ):
                raise RollbackExecutionError(
                    "state_conflict", "Rollback target changed."
                )
            deleted_id = (
                await self.session.execute(
                    delete(CanvasNode)
                    .where(
                        CanvasNode.id == note.id,
                        CanvasNode.canvas_id == approval.canvas_id,
                        CanvasNode.revision == approval.expected_current_revision,
                        CanvasNode.title == note.title,
                        CanvasNode.text == note.text,
                    )
                    .returning(CanvasNode.id)
                )
            ).scalar_one_or_none()
            if deleted_id is None:
                raise RollbackExecutionError(
                    "revision_conflict", "Rollback target changed."
                )
            await self._bump_canvas(approval.canvas_id)
            return None, authoritative_absence_digest()
        if (
            approval.rollback_action
            != ReversibleWriteRollbackAction.NOTE_UPDATE_ROLLBACK.value
            or approval.expected_current_revision <= 0
            or approval.rollback_target_kind != "exact_prior_state"
            or evidence is None
            or approval.rollback_evidence_id != evidence.evidence_id
        ):
            raise RollbackExecutionError(
                "rollback_evidence_invalid", "Rollback evidence is invalid."
            )
        before_state = evidence.before_state
        title = before_state.get("title") if isinstance(before_state, dict) else None
        text = before_state.get("text") if isinstance(before_state, dict) else None
        if (
            not isinstance(title, str)
            or not isinstance(text, str)
            or _note_state_digest({"title": title, "text": text})
            != approval.rollback_target_digest
            or _note_state_digest(_note_state(note)) != effect.after_digest
        ):
            raise RollbackExecutionError(
                "rollback_evidence_invalid", "Rollback evidence is invalid."
            )
        updated = (
            await self.session.execute(
                update(CanvasNode)
                .where(
                    CanvasNode.id == note.id,
                    CanvasNode.canvas_id == approval.canvas_id,
                    CanvasNode.revision == approval.expected_current_revision,
                    CanvasNode.title == note.title,
                    CanvasNode.text == note.text,
                )
                .values(
                    title=title,
                    text=text,
                    revision=CanvasNode.revision + 1,
                )
                .returning(CanvasNode)
            )
        ).scalar_one_or_none()
        if updated is None:
            raise RollbackExecutionError(
                "revision_conflict", "Rollback target changed."
            )
        target_digest = _note_state_digest(_note_state(updated))
        if target_digest != evidence.before_digest:
            raise RollbackExecutionError(
                "rollback_evidence_invalid", "Rollback evidence is invalid."
            )
        await self._bump_canvas(approval.canvas_id)
        return updated.revision, target_digest

    @staticmethod
    def _approval_digest_input(
        *,
        approval: ControlledAgentReversibleWriteRollbackApproval,
        effect: ControlledAgentReversibleWriteEffect,
        evidence: ControlledAgentReversibleWriteRollbackEvidence | None,
        expires_at: datetime,
    ) -> RollbackApprovalDigestInput:
        action = ReversibleWriteAction(effect.action)
        rollback_action = ReversibleWriteRollbackAction(approval.rollback_action)
        target_digest = (
            evidence.before_digest
            if action is ReversibleWriteAction.NOTE_UPDATE and evidence is not None
            else authoritative_absence_digest()
        )
        return RollbackApprovalDigestInput(
            execution_id=effect.execution_id,
            user_id=effect.user_id,
            workspace_id=effect.workspace_id,
            canvas_id=effect.canvas_id,
            note_id=effect.resulting_resource_id,
            proposal_id=effect.proposal_id,
            effect_id=effect.effect_id,
            forward_action=action,
            rollback_action=rollback_action,
            original_plan_digest=effect.plan_digest,
            expected_current_revision=effect.resulting_revision,
            effect_after_state_digest=effect.after_digest,
            rollback_target_kind=approval.rollback_target_kind,
            rollback_target_digest=target_digest,
            rollback_evidence_id=evidence.evidence_id if evidence is not None else None,
            grant_id=approval.grant_id,
            scoped_idempotency_key=approval.scoped_idempotency_key,
            expires_at=expires_at,
        )

    @staticmethod
    def _approval_matches(
        approval: ControlledAgentReversibleWriteRollbackApproval,
        value: RollbackApprovalDigestInput,
    ) -> bool:
        return (
            approval.execution_id == value.execution_id
            and approval.user_id == value.user_id
            and approval.workspace_id == value.workspace_id
            and approval.canvas_id == value.canvas_id
            and approval.note_id == value.note_id
            and approval.proposal_id == value.proposal_id
            and approval.effect_id == value.effect_id
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

    async def _bump_canvas(self, canvas_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Canvas).where(Canvas.id == canvas_id).values(revision=Canvas.revision + 1)
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


__all__ = [
    "AppliedRollback",
    "ReversibleWriteRollbackService",
    "RollbackExecutionError",
]
