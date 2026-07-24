from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

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


class AgentDraftStart(ApiModel):
    canvas_id: uuid.UUID
    instruction: str = Field(min_length=1, max_length=8_000)
    selected_node_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("instruction")
    @classmethod
    def trim_instruction(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("instruction must not be blank")
        return normalized

    @field_validator("selected_node_ids")
    @classmethod
    def unique_selected_nodes(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("selectedNodeIds must not contain duplicates")
        return value


class AgentDraftCitationOut(ApiModel):
    source_id: str
    document_id: uuid.UUID
    document_version: int
    chunk_id: uuid.UUID
    claim: str
    quote: str


class AgentDraftOut(ApiModel):
    execution_id: uuid.UUID
    trace_id: uuid.UUID
    response_id: uuid.UUID
    text: str
    insufficient_evidence: bool
    citations: tuple[AgentDraftCitationOut, ...] = ()
    duplicate: bool = False


class AgentExecutionCancel(ApiModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class AgentExecutionCancelOut(ApiModel):
    execution_id: uuid.UUID
    cancelled: bool
    duplicate: bool
    status: Literal[
        "proposed",
        "awaiting_approval",
        "ready",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "denied",
    ]
    reason_code: str
