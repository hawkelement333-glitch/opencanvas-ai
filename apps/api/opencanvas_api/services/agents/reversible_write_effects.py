"""Atomic, server-authoritative application of approved reversible note effects."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    Canvas,
    CanvasNode,
    ControlledAgentApproval,
    ControlledAgentCapabilityGrant,
    ControlledAgentExecution,
    ControlledAgentPlanSnapshot,
    ControlledAgentReversibleWriteEffect,
    ControlledAgentReversibleWriteProposal,
    ControlledAgentReversibleWriteRollbackEvidence,
    Workspace,
)
from opencanvas_api.services.agents.contracts import (
    ApprovalRecord,
    AuditAttribute,
    AuditEvent,
    CapabilityGrant,
    PlanSnapshot,
    ResourceKind,
    ResourceScope,
    contract_digest,
)
from opencanvas_api.services.agents.persistence import (
    AgentContractIntegrityError,
    ApprovalConsumptionAttempt,
    ControlledAgentRepository,
)
from opencanvas_api.services.agents.reversible_writes import (
    ReversibleWriteAction,
    ReversibleWriteProposal,
)
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import CompleteTraceInput, StartTraceInput, TraceService


class ReversibleEffectError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class AppliedReversibleEffect:
    effect: ControlledAgentReversibleWriteEffect
    duplicate: bool


class ReversibleWriteEffectService:
    """Apply exactly one approved note proposal within the caller's transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        after_mutation: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)
        self.now = now or datetime.now(UTC)
        self.after_mutation = after_mutation

    async def apply(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        idempotency_key: str,
    ) -> AppliedReversibleEffect:
        proposal_row = await self._proposal(authenticated_user_id, workspace_id, execution_id)
        proposal = self._proposal_contract(proposal_row)
        if idempotency_key != proposal.idempotency_key:
            raise ReversibleEffectError("idempotency_conflict", "Effect request conflicts.")
        existing = await self.session.scalar(
            select(ControlledAgentReversibleWriteEffect).where(
                ControlledAgentReversibleWriteEffect.user_id == authenticated_user_id,
                ControlledAgentReversibleWriteEffect.workspace_id == workspace_id,
                ControlledAgentReversibleWriteEffect.canvas_id == proposal.canvas.resource_id,
                ControlledAgentReversibleWriteEffect.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.proposal_id == proposal.proposal_id
                and existing.execution_id == execution_id
            ):
                return AppliedReversibleEffect(existing, True)
            raise ReversibleEffectError("idempotency_conflict", "Effect request conflicts.")

        async with self.session.begin_nested():
            canvas = await self._canvas(
                authenticated_user_id, workspace_id, proposal.canvas.resource_id
            )
            self._assert_proposal_scope(proposal, canvas)
            approval, grant = await self._authority(proposal)
            await self._assert_authority(proposal, approval, grant)
            resource = self._proposal_resource(proposal)
            decision = await self.repository.consume_approval(
                ApprovalConsumptionAttempt(
                    consumption_id=uuid.uuid4(),
                    decision_id=uuid.uuid4(),
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    execution_id=execution_id,
                    approval_id=approval.approval_id,
                    capability=proposal.capability,
                    resource=resource,
                    evaluated_at=self.now,
                )
            )
            if decision.outcome.value != "allow":
                raise ReversibleEffectError(decision.reason_code, "Effect authority is inactive.")
            node, before_state, before_digest = await self._apply_note(proposal, canvas)
            if self.after_mutation is not None:
                await self.after_mutation()
            after_digest = (
                _note_state_digest(_note_state(node))
                if before_state is not None
                else _note_digest(node)
            )
            trace_id = uuid.uuid4()
            trace = TraceService(self.session)
            await trace.start_trace(
                StartTraceInput(
                    trace_id=trace_id,
                    parent_trace_id=proposal_row.trace_id,
                    event_type="reversible_write.effect",
                    actor_id=str(authenticated_user_id),
                    actor_type="user",
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    object_id=node.id,
                    object_type="canvas_node",
                    operation=f"reversible_write.{proposal.action.value}",
                    metadata={
                        "proposalDigest": contract_digest(proposal),
                        "action": proposal.action.value,
                    },
                )
            )
            effect = ControlledAgentReversibleWriteEffect(
                effect_id=uuid.uuid4(),
                execution_id=execution_id,
                proposal_id=proposal.proposal_id,
                approval_id=approval.approval_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                canvas_id=canvas.id,
                idempotency_key=idempotency_key,
                plan_digest=contract_digest(proposal),
                action=proposal.action.value,
                destination_id=proposal.destination.resource_id,
                resource_id=proposal.resource.resource_id
                if proposal.resource is not None
                else None,
                expected_revision=proposal.resource.version
                if proposal.resource is not None
                else None,
                resulting_resource_id=node.id,
                resulting_revision=node.revision,
                before_digest=before_digest,
                after_digest=after_digest,
                outcome="succeeded",
                trace_id=trace_id,
                created_at=self.now,
            )
            self.session.add(effect)
            await self.session.flush()
            if before_state is not None:
                self.session.add(
                    ControlledAgentReversibleWriteRollbackEvidence(
                        evidence_id=uuid.uuid4(),
                        effect_id=effect.effect_id,
                        execution_id=execution_id,
                        proposal_id=proposal.proposal_id,
                        user_id=authenticated_user_id,
                        workspace_id=workspace_id,
                        canvas_id=canvas.id,
                        action=proposal.action.value,
                        note_id=node.id,
                        pre_effect_revision=node.revision - 1,
                        post_effect_revision=node.revision,
                        before_state=before_state,
                        before_digest=before_digest,
                        after_digest=after_digest,
                        created_at=self.now,
                    )
                )
            audit_event_id = uuid.uuid4()
            await self.repository.append_audit_event(
                AuditEvent(
                    event_id=audit_event_id,
                    trace_id=trace_id,
                    execution_id=execution_id,
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    event_type="reversible_write.applied",
                    recorded_at=self.now,
                    attributes=(
                        AuditAttribute(key="action", value=proposal.action.value),
                        AuditAttribute(key="proposal_digest", value=contract_digest(proposal)),
                        AuditAttribute(key="before_digest", value=before_digest),
                        AuditAttribute(key="after_digest", value=after_digest),
                        AuditAttribute(key="resulting_revision", value=node.revision),
                    ),
                )
            )
            await trace.complete_trace(
                CompleteTraceInput(
                    trace_id=trace_id,
                    parent_trace_id=proposal_row.trace_id,
                    event_type="reversible_write.effect",
                    actor_id=str(authenticated_user_id),
                    actor_type="user",
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    object_id=node.id,
                    object_type="canvas_node",
                    operation=f"reversible_write.{proposal.action.value}",
                    metadata={
                        "effectId": str(effect.effect_id),
                        "resultingRevision": node.revision,
                    },
                )
            )
            await DomainEventService(self.session).record(
                CreateDomainEvent(
                    event_type="controlled.effect.committed",
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas.id,
                    subject_id=effect.effect_id,
                    related_id=node.id,
                    actor_user_id=authenticated_user_id,
                    execution_id=execution_id,
                    source_identity=idempotency_key,
                    trace_id=trace_id,
                    audit_event_id=audit_event_id,
                    payload={
                        "action": proposal.action.value,
                        "noteId": str(node.id),
                        "resultingRevision": node.revision,
                    },
                    origin_type="controlled_execution",
                    effect_id=effect.effect_id,
                )
            )
            await self.session.flush()
        return AppliedReversibleEffect(effect, False)

    async def _proposal(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, execution_id: uuid.UUID
    ) -> ControlledAgentReversibleWriteProposal:
        row = await self.session.scalar(
            select(ControlledAgentReversibleWriteProposal).where(
                ControlledAgentReversibleWriteProposal.execution_id == execution_id,
                ControlledAgentReversibleWriteProposal.user_id == user_id,
                ControlledAgentReversibleWriteProposal.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise ReversibleEffectError(
                "proposal_not_found", "Effect proposal not found.", status_code=404
            )
        return row

    @staticmethod
    def _proposal_contract(row: ControlledAgentReversibleWriteProposal) -> ReversibleWriteProposal:
        proposal = ReversibleWriteProposal.model_validate(row.payload)
        if (
            proposal.proposal_id != row.proposal_id
            or contract_digest(proposal) != row.payload_digest
        ):
            raise AgentContractIntegrityError("Stored reversible proposal digest changed.")
        return proposal

    async def _canvas(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, canvas_id: uuid.UUID
    ) -> Canvas:
        canvas = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.owner_id == user_id,
            )
        )
        if canvas is None:
            raise ReversibleEffectError("canvas_not_found", "Canvas not found.", status_code=404)
        return canvas

    async def _authority(
        self, proposal: ReversibleWriteProposal
    ) -> tuple[ApprovalRecord, CapabilityGrant]:
        execution = await self.session.scalar(
            select(ControlledAgentExecution).where(
                ControlledAgentExecution.id == proposal.execution_id,
                ControlledAgentExecution.user_id == proposal.user_id,
                ControlledAgentExecution.workspace_id == proposal.workspace_id,
            )
        )
        plan_row = await self.session.scalar(
            select(ControlledAgentPlanSnapshot).where(
                ControlledAgentPlanSnapshot.execution_id == proposal.execution_id,
                ControlledAgentPlanSnapshot.user_id == proposal.user_id,
                ControlledAgentPlanSnapshot.workspace_id == proposal.workspace_id,
            )
        )
        grant_row = await self.session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == proposal.execution_id,
                ControlledAgentCapabilityGrant.user_id == proposal.user_id,
                ControlledAgentCapabilityGrant.workspace_id == proposal.workspace_id,
            )
        )
        if execution is None or plan_row is None or grant_row is None:
            raise ReversibleEffectError(
                "authority_not_found", "Effect authority is unavailable.", status_code=404
            )
        plan = ControlledAgentRepository._load_contract(
            PlanSnapshot, plan_row.payload, plan_row.payload_digest
        )
        grant = ControlledAgentRepository._load_contract(
            CapabilityGrant, grant_row.payload, grant_row.payload_digest
        )
        approval_row = await self.session.scalar(
            select(ControlledAgentApproval).where(
                ControlledAgentApproval.approval_id == grant.approval_id,
                ControlledAgentApproval.execution_id == proposal.execution_id,
                ControlledAgentApproval.user_id == proposal.user_id,
                ControlledAgentApproval.workspace_id == proposal.workspace_id,
            )
        )
        if approval_row is None:
            raise ReversibleEffectError(
                "approval_not_found", "Effect approval not found.", status_code=404
            )
        approval = ControlledAgentRepository._load_contract(
            ApprovalRecord, approval_row.payload, approval_row.payload_digest
        )
        if (
            execution.plan_digest != plan_row.payload_digest
            or grant.plan_digest != plan_row.payload_digest
            or approval.plan_digest != grant.plan_digest
            or len(plan.actions) != 1
            or plan.actions[0].expected_result_digest != contract_digest(proposal)
        ):
            raise AgentContractIntegrityError("Effect authority digest binding is invalid.")
        return approval, grant

    async def _assert_authority(
        self, proposal: ReversibleWriteProposal, approval: ApprovalRecord, grant: CapabilityGrant
    ) -> None:
        if self.now >= proposal.expires_at or self.now >= approval.expires_at:
            raise ReversibleEffectError("approval_expired", "Effect approval has expired.")
        if self.now >= grant.expires_at:
            raise ReversibleEffectError("grant_expired", "Effect authority has expired.")
        if approval.decision.value != "approved" or grant.approval_id != approval.approval_id:
            raise ReversibleEffectError("approval_inactive", "Effect approval is inactive.")
        if proposal.capability not in grant.capabilities:
            raise ReversibleEffectError("capability_denied", "Effect authority is inactive.")

    @staticmethod
    def _assert_proposal_scope(proposal: ReversibleWriteProposal, canvas: Canvas) -> None:
        if (
            proposal.canvas.kind is not ResourceKind.CANVAS
            or proposal.destination != proposal.canvas
            or proposal.canvas.resource_id != canvas.id
            or proposal.canvas.version != canvas.revision
        ):
            raise ReversibleEffectError("stale_proposal", "Effect proposal is stale.")

    @staticmethod
    def _proposal_resource(proposal: ReversibleWriteProposal) -> ResourceScope:
        return proposal.resource or proposal.canvas

    async def _apply_note(
        self, proposal: ReversibleWriteProposal, canvas: Canvas
    ) -> tuple[CanvasNode, dict[str, str] | None, str | None]:
        if proposal.action is ReversibleWriteAction.NOTE_CREATE:
            node = CanvasNode(
                canvas_id=canvas.id,
                type="note",
                title=proposal.preview.title,
                text=proposal.preview.text,
                position_x=0.0,
                position_y=0.0,
            )
            self.session.add(node)
            await self.session.flush()
            await self._bump_canvas(canvas.id)
            return node, None, None
        if proposal.resource is None or proposal.resource.kind is not ResourceKind.NODE:
            raise ReversibleEffectError("invalid_note_target", "Effect proposal is invalid.")
        current = await self.session.scalar(
            select(CanvasNode).where(
                CanvasNode.id == proposal.resource.resource_id,
                CanvasNode.canvas_id == canvas.id,
                CanvasNode.type == "note",
            )
        )
        if current is None:
            raise ReversibleEffectError("note_not_found", "Note not found.", status_code=404)
        before_state = _note_state(current)
        before_digest = _note_state_digest(before_state)
        updated_node = (
            await self.session.execute(
                update(CanvasNode)
                .where(
                    CanvasNode.id == current.id,
                    CanvasNode.canvas_id == canvas.id,
                    CanvasNode.revision == proposal.resource.version,
                )
                .values(
                    title=proposal.preview.title,
                    text=proposal.preview.text,
                    revision=CanvasNode.revision + 1,
                )
                .returning(CanvasNode)
            )
        ).scalar_one_or_none()
        if updated_node is None:
            raise ReversibleEffectError("stale_revision", "Note revision changed.")
        await self._bump_canvas(canvas.id)
        return updated_node, before_state, before_digest

    async def _bump_canvas(self, canvas_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Canvas).where(Canvas.id == canvas_id).values(revision=Canvas.revision + 1)
        )


def _note_digest(node: CanvasNode) -> str:
    return hashlib.sha256(
        f"{node.id}:{node.revision}:{node.title}:{node.text}".encode()
    ).hexdigest()


def _note_state(node: CanvasNode) -> dict[str, str]:
    """Return the complete mutable state changed by the approved note-update action."""

    return {
        "text": unicodedata.normalize("NFC", node.text),
        "title": unicodedata.normalize("NFC", node.title),
    }


def _note_state_digest(state: dict[str, str]) -> str:
    """Hash the repository's stable JSON representation of restorable note state."""

    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_completed_effect_state(
    effect: ControlledAgentReversibleWriteEffect,
    note: CanvasNode | None,
    evidence: ControlledAgentReversibleWriteRollbackEvidence | None = None,
) -> bool:
    """Fail-closed state verification using the one digest contract for each forward action."""

    if (
        effect.outcome != "succeeded"
        or note is None
        or note.id != effect.resulting_resource_id
        or note.revision != effect.resulting_revision
    ):
        return False
    if effect.action == ReversibleWriteAction.NOTE_CREATE.value:
        return _note_digest(note) == effect.after_digest
    if effect.action != ReversibleWriteAction.NOTE_UPDATE.value or evidence is None:
        return False
    if (
        evidence.effect_id != effect.effect_id
        or evidence.proposal_id != effect.proposal_id
        or evidence.user_id != effect.user_id
        or evidence.workspace_id != effect.workspace_id
        or evidence.canvas_id != effect.canvas_id
        or evidence.note_id != note.id
        or evidence.post_effect_revision != effect.resulting_revision
        or evidence.after_digest != effect.after_digest
        or not isinstance(evidence.before_state, dict)
    ):
        return False
    before_state = evidence.before_state
    title = before_state.get("title")
    text = before_state.get("text")
    if (
        set(before_state) != {"title", "text"}
        or not isinstance(title, str)
        or not isinstance(text, str)
    ):
        return False
    canonical_before_state = {"title": title, "text": text}
    if _note_state_digest(canonical_before_state) != evidence.before_digest:
        return False
    return _note_state_digest(_note_state(note)) == evidence.after_digest


__all__ = [
    "AppliedReversibleEffect",
    "ReversibleEffectError",
    "ReversibleWriteEffectService",
    "verify_completed_effect_state",
]
