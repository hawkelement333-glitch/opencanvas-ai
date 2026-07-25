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


class AgentExecutionHealthOut(ApiModel):
    status: Literal[
        "waiting_claimable",
        "actively_leased",
        "waiting_retry",
        "cancelled",
        "deadline_exceeded",
        "completed",
        "failed",
        "exhausted",
        "inconsistent",
    ]
    lifecycle_status: str | None
    claimable: bool
    terminal: bool
    lease_active: bool
    attempt_count: int
    max_attempts: int
    deadline_at: datetime
    next_retry_at: datetime | None
    safe_reason_code: str | None


class AgentExecutionInspectionOut(ApiModel):
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    schema_version: str
    role: str
    created_at: datetime
    health: AgentExecutionHealthOut
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


class AgentDraftPreparedOut(ApiModel):
    execution_id: uuid.UUID
    status: Literal["ready"]
    duplicate: bool = False


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


class ReversibleWriteProposalStart(ApiModel):
    canvas_id: uuid.UUID
    action: Literal["note.create", "note.update"]
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(max_length=20_000)
    note_id: uuid.UUID | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ReversibleWriteProposalOut(ApiModel):
    execution_id: uuid.UUID
    proposal_id: uuid.UUID
    trace_id: uuid.UUID
    action: Literal["note.create", "note.update"]
    plan_digest: str
    canvas_id: uuid.UUID
    canvas_revision: int
    note_id: uuid.UUID | None = None
    expected_revision: int | None = None
    title: str
    text: str
    expires_at: datetime
    duplicate: bool = False


class ReversibleWriteApprovalStart(ApiModel):
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReversibleWriteApprovalOut(ApiModel):
    execution_id: uuid.UUID
    approval_id: uuid.UUID
    plan_digest: str
    status: Literal["ready"]
    duplicate: bool = False


class ReversibleWriteEffectStart(ApiModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ReversibleWriteEffectOut(ApiModel):
    effect_id: uuid.UUID
    trace_id: uuid.UUID
    action: Literal["note.create", "note.update"]
    note_id: uuid.UUID
    revision: int
    duplicate: bool = False


class ReversibleWriteRollbackReviewOut(ApiModel):
    effect_id: uuid.UUID
    forward_action: str | None = None
    note_id: uuid.UUID | None = None
    effect_revision: int | None = None
    current_revision: int | None = None
    rollback_action: str | None = None
    rollback_target_kind: str | None = None
    required_capability: str | None = None
    eligible: bool
    approval_required: bool
    denial_reason: str | None = None
    conflict: bool


class ReversibleWriteRollbackApprovalStart(ApiModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ReversibleWriteRollbackApprovalOut(ApiModel):
    rollback_approval_id: uuid.UUID
    effect_id: uuid.UUID
    note_id: uuid.UUID
    forward_action: Literal["note.create", "note.update"]
    rollback_action: Literal["note.create.rollback", "note.update.rollback"]
    expected_current_revision: int
    rollback_target_kind: Literal["authoritative_absence", "exact_prior_state"]
    expires_at: datetime
    duplicate: bool = False


class ReversibleWriteRollbackStart(ApiModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ReversibleWriteRollbackOut(ApiModel):
    rollback_result_id: uuid.UUID
    rollback_approval_id: uuid.UUID
    effect_id: uuid.UUID
    note_id: uuid.UUID
    rollback_action: Literal["note.create.rollback", "note.update.rollback"]
    rollback_target_kind: Literal["authoritative_absence", "exact_prior_state"]
    resulting_revision: int | None
    created_at: datetime
    duplicate: bool = False
