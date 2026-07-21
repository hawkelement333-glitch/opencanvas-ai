from __future__ import annotations

import uuid
from datetime import datetime

from opencanvas_api.api.schemas import ApiModel


class AgentContextReferenceOut(ApiModel):
    snapshot_id: uuid.UUID
    digest: str
    captured_at: datetime


class AgentPlanReferenceOut(ApiModel):
    plan_id: uuid.UUID
    digest: str
    created_at: datetime


class AgentStateOut(ApiModel):
    state_id: uuid.UUID
    status: str
    recorded_at: datetime
    safe_reason_code: str | None = None


class AgentGrantOut(ApiModel):
    grant_id: uuid.UUID
    policy_version: str
    role: str
    context_digest: str
    plan_digest: str
    issued_at: datetime
    expires_at: datetime
    approval_required: bool
    approval_id: uuid.UUID | None = None


class AgentRevocationOut(ApiModel):
    revocation_id: uuid.UUID
    grant_id: uuid.UUID
    revoked_at: datetime
    reason_code: str


class AgentApprovalOut(ApiModel):
    approval_id: uuid.UUID
    grant_id: uuid.UUID
    policy_version: str
    decision: str
    context_digest: str
    plan_digest: str
    decided_at: datetime
    expires_at: datetime


class AgentApprovalConsumptionOut(ApiModel):
    consumption_id: uuid.UUID
    approval_id: uuid.UUID
    policy_decision_id: uuid.UUID
    consumed_at: datetime


class AgentPolicyDecisionOut(ApiModel):
    decision_id: uuid.UUID
    policy_version: str
    outcome: str
    reason_code: str
    evaluated_at: datetime
    grant_id: uuid.UUID | None = None
    approval_id: uuid.UUID | None = None
    context_digest: str
    plan_digest: str


class AgentAuditAttributeOut(ApiModel):
    key: str
    value: str | int | bool | None


class AgentAuditEventOut(ApiModel):
    event_id: uuid.UUID
    trace_id: uuid.UUID
    event_type: str
    recorded_at: datetime
    attributes: tuple[AgentAuditAttributeOut, ...] = ()


class AgentExecutionInspectionOut(ApiModel):
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    schema_version: str
    role: str
    created_at: datetime
    context: AgentContextReferenceOut
    plan: AgentPlanReferenceOut
    states: tuple[AgentStateOut, ...] = ()
    grants: tuple[AgentGrantOut, ...] = ()
    revocations: tuple[AgentRevocationOut, ...] = ()
    approvals: tuple[AgentApprovalOut, ...] = ()
    consumptions: tuple[AgentApprovalConsumptionOut, ...] = ()
    policy_decisions: tuple[AgentPolicyDecisionOut, ...] = ()
    audit_events: tuple[AgentAuditEventOut, ...] = ()
