from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    ControlledAgentApproval,
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
    ControlledAgentCapabilityGrant,
    ControlledAgentContextSnapshot,
    ControlledAgentExecution,
    ControlledAgentExecutionState,
    ControlledAgentGrantRevocation,
    ControlledAgentPlanSnapshot,
    ControlledAgentPolicyDecision,
    Workspace,
)
from opencanvas_api.services.agents.contracts import (
    ApprovalRecord,
    AuditEvent,
    Capability,
    CapabilityGrant,
    ContextSnapshot,
    ExecutionRecord,
    ExecutionStateRecord,
    PlanSnapshot,
    PolicyDecision,
    PolicyOutcome,
    ResourceScope,
    RevocationRecord,
    contract_digest,
)
from opencanvas_api.services.agents.policy import PolicyRequest, evaluate_policy


class AgentPersistenceError(RuntimeError):
    pass


class AgentPersistenceNotFound(AgentPersistenceError):
    pass


class AgentContractIntegrityError(AgentPersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class ApprovalConsumptionAttempt:
    consumption_id: uuid.UUID
    decision_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    approval_id: uuid.UUID
    capability: Capability
    resource: ResourceScope
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class AgentInspection:
    execution: ControlledAgentExecution
    context: ControlledAgentContextSnapshot
    plan: ControlledAgentPlanSnapshot
    states: tuple[ControlledAgentExecutionState, ...]
    grants: tuple[ControlledAgentCapabilityGrant, ...]
    revocations: tuple[ControlledAgentGrantRevocation, ...]
    approvals: tuple[ControlledAgentApproval, ...]
    consumptions: tuple[ControlledAgentApprovalConsumption, ...]
    policy_decisions: tuple[ControlledAgentPolicyDecision, ...]
    audit_events: tuple[ControlledAgentAuditEvent, ...]


class ControlledAgentRepository:
    """Append-only writes and ownership-scoped reads for inert control-plane records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append_bundle(
        self,
        *,
        execution: ExecutionRecord,
        context: ContextSnapshot,
        plan: PlanSnapshot,
        grant: CapabilityGrant,
        approval: ApprovalRecord | None = None,
    ) -> None:
        expected_scope = (execution.user_id, execution.workspace_id, execution.execution_id)
        if expected_scope != (context.user_id, context.workspace_id, context.execution_id):
            raise AgentContractIntegrityError("Context ownership does not match execution.")
        if expected_scope != (plan.user_id, plan.workspace_id, plan.execution_id):
            raise AgentContractIntegrityError("Plan ownership does not match execution.")
        if expected_scope != (grant.user_id, grant.workspace_id, grant.execution_id):
            raise AgentContractIntegrityError("Grant ownership does not match execution.")
        if execution.context_snapshot_id != context.snapshot_id:
            raise AgentContractIntegrityError("Execution references a different context snapshot.")
        if execution.plan_id != plan.plan_id or execution.grant_id != grant.grant_id:
            raise AgentContractIntegrityError("Execution references a different plan or grant.")
        context_digest = contract_digest(context)
        plan_digest = contract_digest(plan)
        if {
            execution.context_digest,
            grant.context_digest,
        } != {context_digest} or {execution.plan_digest, grant.plan_digest} != {plan_digest}:
            raise AgentContractIntegrityError("Stored contract digest binding is invalid.")
        if execution.role is not grant.role or execution.role is not plan.role:
            raise AgentContractIntegrityError("Execution role binding is invalid.")
        if approval is not None:
            self._validate_approval_binding(approval, grant)

        self.session.add(
            ControlledAgentExecution(
                id=execution.execution_id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                schema_version=execution.schema_version,
                role=execution.role.value,
                context_snapshot_id=execution.context_snapshot_id,
                context_digest=execution.context_digest,
                plan_id=execution.plan_id,
                plan_digest=execution.plan_digest,
                grant_id=execution.grant_id,
                created_at=execution.created_at,
            )
        )
        await self.session.flush()
        self.session.add_all(
            [
                ControlledAgentContextSnapshot(
                    snapshot_id=context.snapshot_id,
                    execution_id=context.execution_id,
                    user_id=context.user_id,
                    workspace_id=context.workspace_id,
                    schema_version=context.schema_version,
                    payload_digest=context_digest,
                    payload=context.model_dump(mode="json"),
                    captured_at=context.captured_at,
                ),
                ControlledAgentPlanSnapshot(
                    plan_id=plan.plan_id,
                    execution_id=plan.execution_id,
                    user_id=plan.user_id,
                    workspace_id=plan.workspace_id,
                    schema_version=plan.schema_version,
                    payload_digest=plan_digest,
                    payload=plan.model_dump(mode="json"),
                    created_at=plan.created_at,
                ),
                ControlledAgentCapabilityGrant(
                    grant_id=grant.grant_id,
                    execution_id=grant.execution_id,
                    user_id=grant.user_id,
                    workspace_id=grant.workspace_id,
                    schema_version=grant.schema_version,
                    policy_version=grant.policy_version,
                    role=grant.role.value,
                    context_digest=grant.context_digest,
                    plan_digest=grant.plan_digest,
                    payload_digest=contract_digest(grant),
                    payload=grant.model_dump(mode="json"),
                    issued_at=grant.issued_at,
                    expires_at=grant.expires_at,
                    approval_required=grant.approval_required,
                    approval_id=grant.approval_id,
                ),
            ]
        )
        await self.session.flush()
        if approval is not None:
            self.session.add(self._approval_row(approval))
        await self.session.flush()

    async def append_state(self, state: ExecutionStateRecord) -> None:
        self.session.add(
            ControlledAgentExecutionState(
                state_id=state.state_id,
                execution_id=state.execution_id,
                user_id=state.user_id,
                workspace_id=state.workspace_id,
                schema_version=state.schema_version,
                status=state.status.value,
                recorded_at=state.recorded_at,
                safe_reason_code=state.safe_reason_code,
            )
        )
        await self.session.flush()

    async def append_revocation(self, revocation: RevocationRecord) -> None:
        if revocation.subject_kind != "grant":
            raise AgentContractIntegrityError("Only grant revocations belong in this repository.")
        self.session.add(
            ControlledAgentGrantRevocation(
                revocation_id=revocation.revocation_id,
                grant_id=revocation.subject_id,
                execution_id=revocation.execution_id,
                user_id=revocation.user_id,
                workspace_id=revocation.workspace_id,
                schema_version=revocation.schema_version,
                revoked_at=revocation.revoked_at,
                reason_code=revocation.reason_code,
                payload=revocation.model_dump(mode="json"),
            )
        )
        await self.session.flush()

    async def append_audit_event(self, event: AuditEvent) -> None:
        self.session.add(
            ControlledAgentAuditEvent(
                event_id=event.event_id,
                trace_id=event.trace_id,
                execution_id=event.execution_id,
                user_id=event.user_id,
                workspace_id=event.workspace_id,
                schema_version=event.schema_version,
                event_type=event.event_type,
                recorded_at=event.recorded_at,
                attributes=[item.model_dump(mode="json") for item in event.attributes],
            )
        )
        await self.session.flush()

    async def append_policy_decision(self, decision: PolicyDecision) -> None:
        self.session.add(self._policy_row(decision))
        await self.session.flush()

    async def consume_approval(self, attempt: ApprovalConsumptionAttempt) -> PolicyDecision:
        execution = await self._owned_execution(
            attempt.user_id, attempt.workspace_id, attempt.execution_id
        )
        context_row = await self._one_scoped(
            ControlledAgentContextSnapshot,
            attempt.user_id,
            attempt.workspace_id,
            attempt.execution_id,
        )
        plan_row = await self._one_scoped(
            ControlledAgentPlanSnapshot,
            attempt.user_id,
            attempt.workspace_id,
            attempt.execution_id,
        )
        grant_row = await self._one_scoped(
            ControlledAgentCapabilityGrant,
            attempt.user_id,
            attempt.workspace_id,
            attempt.execution_id,
        )
        approval_row = await self.session.scalar(
            select(ControlledAgentApproval).where(
                ControlledAgentApproval.approval_id == attempt.approval_id,
                ControlledAgentApproval.user_id == attempt.user_id,
                ControlledAgentApproval.workspace_id == attempt.workspace_id,
                ControlledAgentApproval.execution_id == attempt.execution_id,
            )
        )
        if approval_row is None:
            raise AgentPersistenceNotFound("Controlled-agent approval not found.")

        context = self._load_contract(
            ContextSnapshot, context_row.payload, context_row.payload_digest
        )
        plan = self._load_contract(PlanSnapshot, plan_row.payload, plan_row.payload_digest)
        grant = self._load_contract(CapabilityGrant, grant_row.payload, grant_row.payload_digest)
        approval = self._load_contract(
            ApprovalRecord, approval_row.payload, approval_row.payload_digest
        )
        if (
            execution.context_digest != context_row.payload_digest
            or execution.plan_digest != plan_row.payload_digest
            or execution.grant_id != grant.grant_id
        ):
            raise AgentContractIntegrityError("Execution references altered contract records.")

        revocation_rows = tuple(
            (
                await self.session.scalars(
                    select(ControlledAgentGrantRevocation).where(
                        ControlledAgentGrantRevocation.user_id == attempt.user_id,
                        ControlledAgentGrantRevocation.workspace_id == attempt.workspace_id,
                        ControlledAgentGrantRevocation.execution_id == attempt.execution_id,
                    )
                )
            ).all()
        )
        revocations = tuple(self._load_revocation(row.payload) for row in revocation_rows)
        consumed_ids = frozenset(
            (
                await self.session.scalars(
                    select(ControlledAgentApprovalConsumption.approval_id).where(
                        ControlledAgentApprovalConsumption.user_id == attempt.user_id,
                        ControlledAgentApprovalConsumption.workspace_id == attempt.workspace_id,
                        ControlledAgentApprovalConsumption.execution_id == attempt.execution_id,
                    )
                )
            ).all()
        )
        request = PolicyRequest(
            decision_id=attempt.decision_id,
            policy_version=grant.policy_version,
            evaluated_at=attempt.evaluated_at,
            user_id=attempt.user_id,
            workspace_id=attempt.workspace_id,
            execution_id=attempt.execution_id,
            capability=attempt.capability,
            resource=attempt.resource,
            context=context,
            plan=plan,
        )
        decision = evaluate_policy(
            request,
            grant=grant,
            approval=approval,
            revocations=revocations,
            consumed_approval_ids=consumed_ids,
        )
        if decision.outcome is not PolicyOutcome.ALLOW:
            await self.append_policy_decision(decision)
            return decision

        try:
            async with self.session.begin_nested():
                self.session.add(self._policy_row(decision))
                await self.session.flush()
                self.session.add(
                    ControlledAgentApprovalConsumption(
                        consumption_id=attempt.consumption_id,
                        approval_id=approval.approval_id,
                        policy_decision_id=decision.decision_id,
                        execution_id=attempt.execution_id,
                        user_id=attempt.user_id,
                        workspace_id=attempt.workspace_id,
                        schema_version=approval.schema_version,
                        consumed_at=attempt.evaluated_at,
                    )
                )
                await self.session.flush()
        except IntegrityError:
            replay = decision.model_copy(
                update={"outcome": PolicyOutcome.DENY, "reason_code": "approval_replayed"}
            )
            await self.append_policy_decision(replay)
            return replay
        return decision

    async def inspect_execution(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> AgentInspection:
        execution = await self._owned_execution(user_id, workspace_id, execution_id)
        context = cast(
            ControlledAgentContextSnapshot,
            await self._one_scoped(
                ControlledAgentContextSnapshot, user_id, workspace_id, execution_id
            ),
        )
        plan = cast(
            ControlledAgentPlanSnapshot,
            await self._one_scoped(
                ControlledAgentPlanSnapshot, user_id, workspace_id, execution_id
            ),
        )

        async def history(model: type[object], order_by: Any) -> tuple[object, ...]:
            statement = (
                select(model)
                .where(
                    model.user_id == user_id,  # type: ignore[attr-defined]
                    model.workspace_id == workspace_id,  # type: ignore[attr-defined]
                    model.execution_id == execution_id,  # type: ignore[attr-defined]
                )
                .order_by(order_by)
                .offset(offset)
                .limit(limit)
            )
            return tuple((await self.session.scalars(statement)).all())

        return AgentInspection(
            execution=execution,
            context=context,
            plan=plan,
            states=cast(
                tuple[ControlledAgentExecutionState, ...],
                await history(
                    ControlledAgentExecutionState, ControlledAgentExecutionState.recorded_at
                ),
            ),
            grants=cast(
                tuple[ControlledAgentCapabilityGrant, ...],
                await history(
                    ControlledAgentCapabilityGrant, ControlledAgentCapabilityGrant.issued_at
                ),
            ),
            revocations=cast(
                tuple[ControlledAgentGrantRevocation, ...],
                await history(
                    ControlledAgentGrantRevocation, ControlledAgentGrantRevocation.revoked_at
                ),
            ),
            approvals=cast(
                tuple[ControlledAgentApproval, ...],
                await history(ControlledAgentApproval, ControlledAgentApproval.decided_at),
            ),
            consumptions=cast(
                tuple[ControlledAgentApprovalConsumption, ...],
                await history(
                    ControlledAgentApprovalConsumption,
                    ControlledAgentApprovalConsumption.consumed_at,
                ),
            ),
            policy_decisions=cast(
                tuple[ControlledAgentPolicyDecision, ...],
                await history(
                    ControlledAgentPolicyDecision, ControlledAgentPolicyDecision.evaluated_at
                ),
            ),
            audit_events=cast(
                tuple[ControlledAgentAuditEvent, ...],
                await history(ControlledAgentAuditEvent, ControlledAgentAuditEvent.recorded_at),
            ),
        )

    async def _owned_execution(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, execution_id: uuid.UUID
    ) -> ControlledAgentExecution:
        execution = await self.session.scalar(
            select(ControlledAgentExecution)
            .join(Workspace, Workspace.id == ControlledAgentExecution.workspace_id)
            .where(
                ControlledAgentExecution.id == execution_id,
                ControlledAgentExecution.user_id == user_id,
                ControlledAgentExecution.workspace_id == workspace_id,
                Workspace.owner_id == user_id,
                Workspace.deleted_at.is_(None),
                Workspace.lifecycle_state != "deleted",
            )
        )
        if execution is None:
            raise AgentPersistenceNotFound("Controlled-agent execution not found.")
        return execution

    async def _one_scoped(
        self,
        model: type[ControlledAgentContextSnapshot]
        | type[ControlledAgentPlanSnapshot]
        | type[ControlledAgentCapabilityGrant],
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> (
        ControlledAgentContextSnapshot
        | ControlledAgentPlanSnapshot
        | ControlledAgentCapabilityGrant
    ):
        row = await self.session.scalar(
            select(model).where(
                model.user_id == user_id,
                model.workspace_id == workspace_id,
                model.execution_id == execution_id,
            )
        )
        if row is None:
            raise AgentPersistenceNotFound("Controlled-agent record not found.")
        return cast(
            ControlledAgentContextSnapshot
            | ControlledAgentPlanSnapshot
            | ControlledAgentCapabilityGrant,
            row,
        )

    @staticmethod
    def _load_contract[
        ContractT: ContextSnapshot | PlanSnapshot | CapabilityGrant | ApprovalRecord
    ](
        contract_type: type[ContractT], payload: dict[str, object], expected_digest: str
    ) -> ContractT:
        try:
            contract = contract_type.model_validate(payload)
        except ValidationError as exc:
            raise AgentContractIntegrityError(
                "Stored controlled-agent contract is malformed."
            ) from exc
        if contract_digest(contract) != expected_digest:
            raise AgentContractIntegrityError("Stored controlled-agent contract digest changed.")
        return cast(ContractT, contract)

    @staticmethod
    def _load_revocation(payload: dict[str, object]) -> RevocationRecord:
        try:
            return RevocationRecord.model_validate(payload)
        except ValidationError as exc:
            raise AgentContractIntegrityError("Stored revocation contract is malformed.") from exc

    @staticmethod
    def _validate_approval_binding(approval: ApprovalRecord, grant: CapabilityGrant) -> None:
        if (
            approval.approval_id != grant.approval_id
            or approval.grant_id != grant.grant_id
            or approval.user_id != grant.user_id
            or approval.workspace_id != grant.workspace_id
            or approval.execution_id != grant.execution_id
            or approval.context_digest != grant.context_digest
            or approval.plan_digest != grant.plan_digest
            or approval.capabilities != grant.capabilities
            or approval.resources != grant.resources
        ):
            raise AgentContractIntegrityError("Approval binding does not match its grant.")

    @staticmethod
    def _approval_row(approval: ApprovalRecord) -> ControlledAgentApproval:
        return ControlledAgentApproval(
            approval_id=approval.approval_id,
            grant_id=approval.grant_id,
            execution_id=approval.execution_id,
            user_id=approval.user_id,
            workspace_id=approval.workspace_id,
            schema_version=approval.schema_version,
            policy_version=approval.policy_version,
            decision=approval.decision.value,
            context_digest=approval.context_digest,
            plan_digest=approval.plan_digest,
            payload_digest=contract_digest(approval),
            payload=approval.model_dump(mode="json"),
            decided_at=approval.decided_at,
            expires_at=approval.expires_at,
        )

    @staticmethod
    def _policy_row(decision: PolicyDecision) -> ControlledAgentPolicyDecision:
        return ControlledAgentPolicyDecision(
            decision_id=decision.decision_id,
            execution_id=decision.execution_id,
            user_id=decision.user_id,
            workspace_id=decision.workspace_id,
            schema_version=decision.schema_version,
            policy_version=decision.policy_version,
            outcome=decision.outcome.value,
            reason_code=decision.reason_code,
            evaluated_at=decision.evaluated_at,
            grant_id=decision.grant_id,
            approval_id=decision.approval_id,
            context_digest=decision.context_digest,
            plan_digest=decision.plan_digest,
        )


__all__ = [
    "AgentContractIntegrityError",
    "AgentInspection",
    "AgentPersistenceError",
    "AgentPersistenceNotFound",
    "ApprovalConsumptionAttempt",
    "ControlledAgentRepository",
]
