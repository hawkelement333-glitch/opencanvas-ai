from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from opencanvas_api.services.agents.contracts import (
    SCHEMA_VERSION,
    Capability,
    ContractModel,
    Digest,
    RiskClass,
    _require_aware_utc,
    contract_digest,
)


class ControlledAction(StrEnum):
    GENERATE_GROUNDED_DRAFT = "generate_grounded_draft"


class ExecutionStage(StrEnum):
    VALIDATE_AUTHORITY = "validate_authority"
    LOAD_IMMUTABLE_CONTEXT = "load_immutable_context"
    RETRIEVE_SELECTED_EVIDENCE = "retrieve_selected_evidence"
    GENERATE_GROUNDED_DRAFT = "generate_grounded_draft"
    VALIDATE_CITATIONS = "validate_citations"
    RECORD_AND_RETURN = "record_and_return"


GROUND_DRAFT_STAGES = tuple(ExecutionStage)


class ActionBoundary(ContractModel):
    action: ControlledAction
    allowed_capabilities: tuple[Capability, ...]
    maximum_risk: RiskClass
    allows_workspace_mutation: Literal[False] = False
    allows_external_effects: Literal[False] = False
    allows_delegation: Literal[False] = False


ACTION_REGISTRY = MappingProxyType(
    {
        ControlledAction.GENERATE_GROUNDED_DRAFT: ActionBoundary(
            action=ControlledAction.GENERATE_GROUNDED_DRAFT,
            allowed_capabilities=(
                Capability.CANVAS_SNAPSHOT_READ,
                Capability.CONTEXT_SELECTED_READ,
                Capability.DOCUMENT_VERSION_READ,
                Capability.RETRIEVAL_SELECTED_SEARCH,
                Capability.DRAFT_ANSWER_CREATE,
                Capability.TRACE_SCOPED_READ,
            ),
            maximum_risk=RiskClass.R1_DRAFT,
        )
    }
)


class ControlledExecutionRequest(ContractModel):
    """Trusted internal request; user identity must come from server authentication."""

    contract_kind: Literal["controlled_execution_request"] = "controlled_execution_request"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    context_snapshot_id: uuid.UUID
    expected_context_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: uuid.UUID
    expected_plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    action: ControlledAction
    grant_id: uuid.UUID
    approval_id: uuid.UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=64)

    @field_validator("idempotency_key", "client_request_id", "correlation_id")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("request identifiers must not contain surrounding whitespace")
        return value


class ControlledExecutionPlan(ContractModel):
    contract_kind: Literal["controlled_execution_plan"] = "controlled_execution_plan"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    plan_id: uuid.UUID
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    action: ControlledAction
    created_at: datetime
    stages: tuple[ExecutionStage, ...] = GROUND_DRAFT_STAGES

    _created_at_is_utc = field_validator("created_at")(_require_aware_utc)

    @model_validator(mode="after")
    def plan_is_closed_and_ordered(self) -> Self:
        if self.action is not ControlledAction.GENERATE_GROUNDED_DRAFT:
            raise ValueError("unsupported controlled action")
        if self.stages != GROUND_DRAFT_STAGES:
            raise ValueError("controlled execution stages are fixed and ordered")
        return self


class IdempotencyFingerprint(ContractModel):
    contract_kind: Literal["controlled_execution_idempotency"] = "controlled_execution_idempotency"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    action: ControlledAction
    idempotency_key: str
    context_snapshot_id: uuid.UUID
    context_digest: Digest
    plan_id: uuid.UUID
    plan_digest: Digest
    grant_id: uuid.UUID
    approval_id: uuid.UUID | None = None


def idempotency_digest(request: ControlledExecutionRequest) -> Digest:
    """Bind retry identity to authority and immutable content, not transport metadata."""

    return contract_digest(
        IdempotencyFingerprint(
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            canvas_id=request.canvas_id,
            action=request.action,
            idempotency_key=request.idempotency_key,
            context_snapshot_id=request.context_snapshot_id,
            context_digest=request.expected_context_digest,
            plan_id=request.plan_id,
            plan_digest=request.expected_plan_digest,
            grant_id=request.grant_id,
            approval_id=request.approval_id,
        )
    )


__all__ = [
    "ACTION_REGISTRY",
    "GROUND_DRAFT_STAGES",
    "ActionBoundary",
    "ControlledAction",
    "ControlledExecutionPlan",
    "ControlledExecutionRequest",
    "ExecutionStage",
    "IdempotencyFingerprint",
    "idempotency_digest",
]
