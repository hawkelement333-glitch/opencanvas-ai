from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.agent_schemas import (
    AgentApprovalConsumptionOut,
    AgentApprovalOut,
    AgentAuditAttributeOut,
    AgentAuditEventOut,
    AgentContextReferenceOut,
    AgentExecutionInspectionOut,
    AgentGrantOut,
    AgentPlanReferenceOut,
    AgentPolicyDecisionOut,
    AgentRevocationOut,
    AgentStateOut,
)
from opencanvas_api.api.dependencies import PrincipalDep, get_session
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.serialization import utc
from opencanvas_api.services.agents.persistence import (
    AgentInspection,
    AgentPersistenceNotFound,
    ControlledAgentRepository,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/agent-executions")
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{execution_id}", response_model=AgentExecutionInspectionOut)
async def inspect_agent_execution(
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> AgentExecutionInspectionOut:
    try:
        inspection = await ControlledAgentRepository(session).inspect_execution(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            limit=limit,
            offset=offset,
        )
    except AgentPersistenceNotFound as exc:
        raise ApiError(
            http_status.HTTP_404_NOT_FOUND,
            "agent_execution_not_found",
            "Controlled-agent execution not found.",
        ) from exc
    return _inspection_out(inspection)


def _inspection_out(inspection: AgentInspection) -> AgentExecutionInspectionOut:
    execution = inspection.execution
    return AgentExecutionInspectionOut(
        execution_id=execution.id,
        user_id=execution.user_id,
        workspace_id=execution.workspace_id,
        schema_version=execution.schema_version,
        role=execution.role,
        created_at=utc(execution.created_at),
        context=AgentContextReferenceOut(
            snapshot_id=inspection.context.snapshot_id,
            digest=inspection.context.payload_digest,
            captured_at=utc(inspection.context.captured_at),
        ),
        plan=AgentPlanReferenceOut(
            plan_id=inspection.plan.plan_id,
            digest=inspection.plan.payload_digest,
            created_at=utc(inspection.plan.created_at),
        ),
        states=tuple(
            AgentStateOut(
                state_id=row.state_id,
                status=row.status,
                recorded_at=utc(row.recorded_at),
                safe_reason_code=row.safe_reason_code,
            )
            for row in inspection.states
        ),
        grants=tuple(
            AgentGrantOut(
                grant_id=row.grant_id,
                policy_version=row.policy_version,
                role=row.role,
                context_digest=row.context_digest,
                plan_digest=row.plan_digest,
                issued_at=utc(row.issued_at),
                expires_at=utc(row.expires_at),
                approval_required=row.approval_required,
                approval_id=row.approval_id,
            )
            for row in inspection.grants
        ),
        revocations=tuple(
            AgentRevocationOut(
                revocation_id=row.revocation_id,
                grant_id=row.grant_id,
                revoked_at=utc(row.revoked_at),
                reason_code=row.reason_code,
            )
            for row in inspection.revocations
        ),
        approvals=tuple(
            AgentApprovalOut(
                approval_id=row.approval_id,
                grant_id=row.grant_id,
                policy_version=row.policy_version,
                decision=row.decision,
                context_digest=row.context_digest,
                plan_digest=row.plan_digest,
                decided_at=utc(row.decided_at),
                expires_at=utc(row.expires_at),
            )
            for row in inspection.approvals
        ),
        consumptions=tuple(
            AgentApprovalConsumptionOut(
                consumption_id=row.consumption_id,
                approval_id=row.approval_id,
                policy_decision_id=row.policy_decision_id,
                consumed_at=utc(row.consumed_at),
            )
            for row in inspection.consumptions
        ),
        policy_decisions=tuple(
            AgentPolicyDecisionOut(
                decision_id=row.decision_id,
                policy_version=row.policy_version,
                outcome=row.outcome,
                reason_code=row.reason_code,
                evaluated_at=utc(row.evaluated_at),
                grant_id=row.grant_id,
                approval_id=row.approval_id,
                context_digest=row.context_digest,
                plan_digest=row.plan_digest,
            )
            for row in inspection.policy_decisions
        ),
        audit_events=tuple(
            AgentAuditEventOut(
                event_id=row.event_id,
                trace_id=row.trace_id,
                event_type=row.event_type,
                recorded_at=utc(row.recorded_at),
                attributes=tuple(
                    AgentAuditAttributeOut.model_validate(item) for item in row.attributes
                ),
            )
            for row in inspection.audit_events
        ),
    )
