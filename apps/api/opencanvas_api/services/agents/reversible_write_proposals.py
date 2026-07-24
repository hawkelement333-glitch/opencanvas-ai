"""Server-owned, review-only proposal and approval foundation for M4.3.

No method in this module creates or updates a canvas node.  Approval is persisted
for a later effect boundary and is deliberately not consumed here.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    Canvas,
    CanvasNode,
    ControlledAgentApproval,
    ControlledAgentCapabilityGrant,
    ControlledAgentReversibleWriteProposal,
    Workspace,
)
from opencanvas_api.services.agents.contracts import (
    AgentRole,
    ApprovalDecision,
    ApprovalRecord,
    AuditAttribute,
    AuditEvent,
    Capability,
    CapabilityGrant,
    ContextResource,
    ContextSnapshot,
    ExecutionRecord,
    ExecutionStateRecord,
    ExecutionStatus,
    PlanAction,
    PlanSnapshot,
    ResourceKind,
    ResourceScope,
    RiskClass,
    contract_digest,
)
from opencanvas_api.services.agents.persistence import (
    AgentContractIntegrityError,
    ControlledAgentRepository,
)
from opencanvas_api.services.agents.reversible_writes import (
    NotePreview,
    ReversibleWriteAction,
    ReversibleWriteProposal,
)

POLICY_VERSION = "reversible-write-v1"
PROPOSAL_TTL = timedelta(minutes=5)


class ReversibleProposalError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class PreparedReversibleProposal:
    proposal: ReversibleWriteProposal
    trace_id: uuid.UUID
    approval_id: uuid.UUID
    duplicate: bool


class ReversibleWriteProposalService:
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)
        self.now = now or datetime.now(UTC)

    async def prepare(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        action: ReversibleWriteAction,
        title: str,
        text: str,
        note_id: uuid.UUID | None,
        expected_revision: int | None,
        idempotency_key: str,
    ) -> PreparedReversibleProposal:
        canvas = await self._owned_canvas(authenticated_user_id, workspace_id, canvas_id)
        existing = await self.session.scalar(
            select(ControlledAgentReversibleWriteProposal).where(
                ControlledAgentReversibleWriteProposal.user_id == authenticated_user_id,
                ControlledAgentReversibleWriteProposal.workspace_id == workspace_id,
                ControlledAgentReversibleWriteProposal.canvas_id == canvas_id,
                ControlledAgentReversibleWriteProposal.action == action.value,
                ControlledAgentReversibleWriteProposal.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            proposal = self._proposal_from_row(existing)
            if (
                proposal.preview != NotePreview(title=title, text=text)
                or (proposal.resource.resource_id if proposal.resource is not None else None)
                != note_id
            ):
                raise ReversibleProposalError(
                    "idempotency_conflict",
                    "The idempotency key was already used for a different proposal.",
                )
            existing_grant = await self.session.scalar(
                select(ControlledAgentCapabilityGrant).where(
                    ControlledAgentCapabilityGrant.execution_id == existing.execution_id,
                    ControlledAgentCapabilityGrant.user_id == authenticated_user_id,
                    ControlledAgentCapabilityGrant.workspace_id == workspace_id,
                )
            )
            if existing_grant is None or existing_grant.approval_id is None:
                raise AgentContractIntegrityError("Proposal grant binding is missing.")
            return PreparedReversibleProposal(
                proposal, existing.trace_id, existing_grant.approval_id, True
            )

        canvas_scope = ResourceScope(
            kind=ResourceKind.CANVAS, resource_id=canvas.id, version=canvas.revision
        )
        resource = await self._resolve_note(
            action=action,
            canvas_id=canvas.id,
            note_id=note_id,
            expected_revision=expected_revision,
        )
        capability = (
            Capability.CANVAS_NOTE_CREATE
            if action is ReversibleWriteAction.NOTE_CREATE
            else Capability.CANVAS_NOTE_UPDATE
        )
        execution_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"opencanvas:reversible-proposal:{authenticated_user_id}:{workspace_id}:"
            f"{canvas_id}:{action.value}:{idempotency_key}",
        )
        proposal = ReversibleWriteProposal(
            proposal_id=uuid.uuid4(),
            execution_id=execution_id,
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            canvas=canvas_scope,
            action=action,
            capability=capability,
            destination=canvas_scope,
            resource=resource,
            preview=NotePreview(title=title, text=text),
            created_at=self.now,
            expires_at=self.now + PROPOSAL_TTL,
            idempotency_key=idempotency_key,
        )
        context = ContextSnapshot(
            snapshot_id=uuid.uuid4(),
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            captured_at=self.now,
            resources=(
                ContextResource(
                    scope=canvas_scope,
                    content_digest=hashlib.sha256(
                        f"canvas:{canvas.id}:{canvas.revision}".encode()
                    ).hexdigest(),
                ),
            ),
        )
        plan_resource = resource or canvas_scope
        plan = PlanSnapshot(
            plan_id=uuid.uuid4(),
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            role=AgentRole.CONTROLLED_ACTION_EXECUTOR,
            created_at=self.now,
            actions=(
                PlanAction(
                    action_id=uuid.uuid4(),
                    ordinal=0,
                    capability=capability,
                    resource=plan_resource,
                    risk_class=RiskClass.R3_DURABLE_WRITE,
                    expected_result_digest=contract_digest(proposal),
                ),
            ),
        )
        approval_id = uuid.uuid4()
        grant = CapabilityGrant(
            grant_id=uuid.uuid4(),
            policy_version=POLICY_VERSION,
            issuing_service="reversible-write-proposal-service",
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            role=AgentRole.CONTROLLED_ACTION_EXECUTOR,
            capabilities=(capability,),
            resources=(canvas_scope,) if resource is None else (canvas_scope, resource),
            context_digest=contract_digest(context),
            plan_digest=contract_digest(plan),
            issued_at=self.now,
            expires_at=proposal.expires_at,
            approval_required=True,
            approval_id=approval_id,
        )
        execution = ExecutionRecord(
            execution_id=execution_id,
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            role=AgentRole.CONTROLLED_ACTION_EXECUTOR,
            context_snapshot_id=context.snapshot_id,
            context_digest=contract_digest(context),
            plan_id=plan.plan_id,
            plan_digest=contract_digest(plan),
            grant_id=grant.grant_id,
            created_at=self.now,
        )
        trace_id = uuid.uuid4()
        await self.repository.append_bundle(
            execution=execution, context=context, plan=plan, grant=grant
        )
        self.session.add(
            ControlledAgentReversibleWriteProposal(
                proposal_id=proposal.proposal_id,
                execution_id=execution_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                action=action.value,
                idempotency_key=idempotency_key,
                payload_digest=contract_digest(proposal),
                payload=proposal.model_dump(mode="json"),
                trace_id=trace_id,
                created_at=proposal.created_at,
                expires_at=proposal.expires_at,
            )
        )
        await self.repository.append_state(
            ExecutionStateRecord(
                state_id=uuid.uuid4(),
                execution_id=execution_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                status=ExecutionStatus.PROPOSED,
                recorded_at=self.now,
            )
        )
        await self.repository.append_state(
            ExecutionStateRecord(
                state_id=uuid.uuid4(),
                execution_id=execution_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                status=ExecutionStatus.AWAITING_APPROVAL,
                recorded_at=self.now,
            )
        )
        await self.repository.append_audit_event(
            AuditEvent(
                event_id=uuid.uuid4(),
                trace_id=trace_id,
                execution_id=execution_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                event_type="reversible_write.proposed",
                recorded_at=self.now,
                attributes=(
                    AuditAttribute(key="action", value=action.value),
                    AuditAttribute(key="proposal_digest", value=contract_digest(proposal)),
                ),
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ReversibleProposalError(
                "idempotency_conflict", "Proposal already exists."
            ) from exc
        return PreparedReversibleProposal(proposal, trace_id, approval_id, False)

    async def approve(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        presented_plan_digest: str,
        session_id: uuid.UUID,
    ) -> tuple[PreparedReversibleProposal, bool]:
        row = await self.session.scalar(
            select(ControlledAgentReversibleWriteProposal).where(
                ControlledAgentReversibleWriteProposal.execution_id == execution_id,
                ControlledAgentReversibleWriteProposal.user_id == authenticated_user_id,
                ControlledAgentReversibleWriteProposal.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise ReversibleProposalError(
                "proposal_not_found", "Proposal not found.", status_code=404
            )
        proposal = self._proposal_from_row(row)
        digest = contract_digest(proposal)
        if presented_plan_digest != digest:
            raise ReversibleProposalError("proposal_digest_mismatch", "Proposal changed.")
        if self.now >= proposal.expires_at:
            raise ReversibleProposalError("proposal_expired", "Proposal has expired.")
        await self._assert_current(proposal)
        grant_row = await self.session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == execution_id,
                ControlledAgentCapabilityGrant.user_id == authenticated_user_id,
                ControlledAgentCapabilityGrant.workspace_id == workspace_id,
            )
        )
        if grant_row is None:
            raise AgentContractIntegrityError("Proposal grant is missing.")
        grant = ControlledAgentRepository._load_contract(
            CapabilityGrant, grant_row.payload, grant_row.payload_digest
        )
        if self.now >= grant.expires_at or grant.approval_id is None:
            raise ReversibleProposalError("grant_inactive", "Proposal authority is inactive.")
        existing = await self.session.scalar(
            select(ControlledAgentApproval).where(
                ControlledAgentApproval.approval_id == grant.approval_id
            )
        )
        prepared = PreparedReversibleProposal(
            proposal, row.trace_id, grant.approval_id, existing is not None
        )
        if existing is not None:
            stored = ControlledAgentRepository._load_contract(
                ApprovalRecord, existing.payload, existing.payload_digest
            )
            if (
                stored.plan_digest != grant.plan_digest
                or stored.decision is not ApprovalDecision.APPROVED
            ):
                raise ReversibleProposalError(
                    "approval_replayed", "Proposal approval was already decided."
                )
            return prepared, True
        approval = ApprovalRecord(
            approval_id=grant.approval_id,
            session_id=session_id,
            policy_version=grant.policy_version,
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            grant_id=grant.grant_id,
            decision=ApprovalDecision.APPROVED,
            capabilities=grant.capabilities,
            resources=grant.resources,
            context_digest=grant.context_digest,
            plan_digest=grant.plan_digest,
            decided_at=self.now,
            expires_at=proposal.expires_at,
        )
        await self.repository.append_approval(approval, grant)
        await self.repository.append_state(
            ExecutionStateRecord(
                state_id=uuid.uuid4(),
                execution_id=execution_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                status=ExecutionStatus.READY,
                recorded_at=self.now,
            )
        )
        await self.repository.append_audit_event(
            AuditEvent(
                event_id=uuid.uuid4(),
                trace_id=row.trace_id,
                execution_id=execution_id,
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                event_type="reversible_write.approved",
                recorded_at=self.now,
                attributes=(AuditAttribute(key="proposal_digest", value=digest),),
            )
        )
        return prepared, False

    async def _owned_canvas(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, canvas_id: uuid.UUID
    ) -> Canvas:
        canvas = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.owner_id == user_id,
                Workspace.deleted_at.is_(None),
                Workspace.lifecycle_state != "deleted",
            )
        )
        if canvas is None:
            raise ReversibleProposalError("canvas_not_found", "Canvas not found.", status_code=404)
        return canvas

    async def _resolve_note(
        self,
        *,
        action: ReversibleWriteAction,
        canvas_id: uuid.UUID,
        note_id: uuid.UUID | None,
        expected_revision: int | None,
    ) -> ResourceScope | None:
        if action is ReversibleWriteAction.NOTE_CREATE:
            if note_id is not None or expected_revision is not None:
                raise ReversibleProposalError(
                    "invalid_note_target", "Note creation has no existing note.", status_code=400
                )
            return None
        if note_id is None or expected_revision is None:
            raise ReversibleProposalError(
                "note_target_required",
                "Note update requires an exact note revision.",
                status_code=400,
            )
        node = await self.session.scalar(
            select(CanvasNode).where(
                CanvasNode.id == note_id,
                CanvasNode.canvas_id == canvas_id,
                CanvasNode.type == "note",
            )
        )
        if node is None:
            raise ReversibleProposalError("note_not_found", "Note not found.", status_code=404)
        if node.revision != expected_revision:
            raise ReversibleProposalError("stale_revision", "Note revision changed.")
        return ResourceScope(kind=ResourceKind.NODE, resource_id=node.id, version=node.revision)

    async def _assert_current(self, proposal: ReversibleWriteProposal) -> None:
        canvas = await self._owned_canvas(
            proposal.user_id, proposal.workspace_id, proposal.canvas.resource_id
        )
        if canvas.revision != proposal.canvas.version:
            raise ReversibleProposalError("stale_proposal", "Canvas revision changed.")
        if proposal.resource is not None:
            await self._resolve_note(
                action=proposal.action,
                canvas_id=canvas.id,
                note_id=proposal.resource.resource_id,
                expected_revision=proposal.resource.version,
            )

    @staticmethod
    def _proposal_from_row(row: ControlledAgentReversibleWriteProposal) -> ReversibleWriteProposal:
        proposal = ReversibleWriteProposal.model_validate(row.payload)
        if (
            proposal.proposal_id != row.proposal_id
            or contract_digest(proposal) != row.payload_digest
        ):
            raise AgentContractIntegrityError("Stored reversible proposal digest changed.")
        return proposal


__all__ = [
    "PreparedReversibleProposal",
    "ReversibleProposalError",
    "ReversibleWriteProposalService",
]
