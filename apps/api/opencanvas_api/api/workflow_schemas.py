from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, field_validator

from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.services.workflows import (
    MAX_DEPENDENCIES_PER_STEP,
    MAX_DURATION_SECONDS,
    MAX_RETRIES_PER_STEP,
    MAX_SELECTED_CONTEXT,
    MAX_WORKFLOW_STEPS,
    WorkflowKind,
    WorkflowStepType,
)


class WorkflowStepIn(ApiModel):
    step_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    step_type: WorkflowStepType
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_DEPENDENCIES_PER_STEP)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    max_attempts: int = Field(default=1, ge=1, le=MAX_RETRIES_PER_STEP + 1)
    compensation_step_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )

    @field_validator("depends_on")
    @classmethod
    def unique_dependencies(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("dependsOn must not contain duplicates")
        return value


class WorkflowVersionIn(ApiModel):
    steps: list[WorkflowStepIn] = Field(min_length=1, max_length=MAX_WORKFLOW_STEPS)
    input_schema_version: Literal["workflow-input-v1"] = "workflow-input-v1"
    output_schema_version: Literal["controlled-workflow-output-v1"] = (
        "controlled-workflow-output-v1"
    )
    max_duration_seconds: int = Field(
        default=MAX_DURATION_SECONDS,
        ge=1,
        le=MAX_DURATION_SECONDS,
    )
    max_retries_per_step: int = Field(
        default=MAX_RETRIES_PER_STEP,
        ge=0,
        le=MAX_RETRIES_PER_STEP,
    )
    compensation_policy: Literal["none", "predefined_saga"] = "none"


class WorkflowDraftCreate(ApiModel):
    kind: WorkflowKind
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1_000)
    version: WorkflowVersionIn
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class WorkflowVersionCreate(ApiModel):
    version: WorkflowVersionIn
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class WorkflowVersionOut(ApiModel):
    version_id: uuid.UUID
    version_number: int
    lifecycle_state: str
    schema_version: str
    input_schema_version: str
    output_schema_version: str
    content_digest: str
    max_steps: int
    max_duration_seconds: int
    max_retries_per_step: int
    compensation_policy: str
    supersedes_version_id: uuid.UUID | None
    trace_id: uuid.UUID
    created_at: datetime


class WorkflowDefinitionOut(ApiModel):
    definition_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    kind: str
    name: str
    description: str
    schema_version: str
    trace_id: uuid.UUID
    created_at: datetime
    versions: list[WorkflowVersionOut]
    duplicate: bool = False


class WorkflowExecutionStart(ApiModel):
    version_id: uuid.UUID
    query: str = Field(min_length=1, max_length=4_000)
    selected_object_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=MAX_SELECTED_CONTEXT,
    )
    seed_object_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=MAX_SELECTED_CONTEXT,
    )
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    @field_validator("selected_object_ids", "seed_object_ids")
    @classmethod
    def unique_object_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("object identifiers must be unique")
        return value


class WorkflowStepExecutionOut(ApiModel):
    step_execution_id: uuid.UUID
    step_key: str
    step_type: str
    depends_on: list[str]
    capability: str
    risk_class: str
    requested_action: str | None
    affected_resource_id: uuid.UUID | None
    status: str
    attempt_count: int
    max_attempts: int
    approval_required: bool
    controlled_execution_id: uuid.UUID | None
    approval_id: uuid.UUID | None
    retrieval_id: uuid.UUID | None
    evidence_bundle_id: uuid.UUID | None
    effect_id: uuid.UUID | None
    rollback_result_id: uuid.UUID | None
    safe_failure_class: str | None
    output_digest: str | None
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowExecutionOut(ApiModel):
    execution_id: uuid.UUID
    definition_id: uuid.UUID
    version_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    status: str
    outcome: str | None
    plan_id: uuid.UUID
    plan_digest: str
    input_digest: str
    graph_revision: int
    selected_object_ids: list[uuid.UUID]
    output: dict[str, JsonValue] | None
    output_digest: str | None
    trace_id: uuid.UUID
    created_at: datetime
    deadline_at: datetime
    cancel_requested_at: datetime | None
    completed_at: datetime | None
    steps: list[WorkflowStepExecutionOut]
    duplicate: bool = False


class WorkflowApprovalDecision(ApiModel):
    decision: Literal["approved", "denied"]


__all__ = [
    "WorkflowApprovalDecision",
    "WorkflowDefinitionOut",
    "WorkflowDraftCreate",
    "WorkflowExecutionOut",
    "WorkflowExecutionStart",
    "WorkflowStepExecutionOut",
    "WorkflowStepIn",
    "WorkflowVersionCreate",
    "WorkflowVersionIn",
    "WorkflowVersionOut",
]
