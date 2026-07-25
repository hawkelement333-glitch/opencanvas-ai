from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, field_validator

from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.services.agent_studio import (
    AgentKind,
    Audience,
    EvaluationOutcome,
    Formality,
    ProposalKind,
    ReadingLevel,
    TechnicalDepth,
    Verbosity,
)
from opencanvas_api.services.agents.contracts import Capability, ResourceKind, RiskClass


class AgentLimitsIn(ApiModel):
    max_workflow_executions: int = Field(default=1, ge=1, le=8)
    max_model_calls: int = Field(default=4, ge=0, le=16)
    max_retrieval_calls: int = Field(default=4, ge=0, le=16)
    max_effects: int = Field(default=1, ge=0, le=4)
    max_approvals: int = Field(default=2, ge=0, le=8)
    max_retries: int = Field(default=2, ge=0, le=3)
    max_duration_seconds: int = Field(default=300, ge=1, le=900)
    max_input_chars: int = Field(default=20_000, ge=1, le=60_000)
    max_output_chars: int = Field(default=20_000, ge=1, le=40_000)
    max_evidence_bundle_requests: int = Field(default=1, ge=0, le=4)


class AgentCapabilityRequirementIn(ApiModel):
    capability: Capability
    resource_kind: ResourceKind


class AgentCommunicationPolicyIn(ApiModel):
    profile_version_id: uuid.UUID | None = None
    require_human_acceptance: bool = True


class AgentVersionIn(ApiModel):
    schema_version: Literal["bounded-agent-definition-v1"] = "bounded-agent-definition-v1"
    purpose: str = Field(min_length=1, max_length=2_000)
    system_instruction: str = Field(min_length=1, max_length=8_000)
    workflow_version_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    capability_requirements: list[AgentCapabilityRequirementIn] = Field(
        min_length=1,
        max_length=32,
    )
    selected_context_policy: Literal["required_explicit", "optional_explicit"] = "required_explicit"
    provider: Literal["mock", "openai"] = "mock"
    model: str = Field(min_length=1, max_length=160)
    limits: AgentLimitsIn = Field(default_factory=AgentLimitsIn)
    communication_policy: AgentCommunicationPolicyIn = Field(
        default_factory=AgentCommunicationPolicyIn
    )
    evaluation_policy: Literal["human_review", "deterministic_evidence_review"] = "human_review"
    risk_class: RiskClass = RiskClass.R1_DRAFT

    @field_validator("purpose", "system_instruction", "model")
    @classmethod
    def trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("agent definition text must not be blank")
        return normalized

    @field_validator("workflow_version_ids")
    @classmethod
    def unique_workflows(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("workflowVersionIds must be unique")
        return value


class AgentCreateIn(ApiModel):
    kind: AgentKind
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1_000)
    version: AgentVersionIn
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class AgentVersionCreateIn(ApiModel):
    version: AgentVersionIn
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class AgentCapabilityRequirementOut(ApiModel):
    capability: str
    resource_kind: str


class AgentWorkflowBindingOut(ApiModel):
    workflow_version_id: uuid.UUID
    workflow_digest: str
    ordinal: int


class AgentVersionOut(ApiModel):
    version_id: uuid.UUID
    version_number: int
    lifecycle_state: str
    schema_version: str
    purpose: str
    prompt_template_version: str
    selected_context_policy: str
    provider: str
    model: str
    limits: dict[str, JsonValue]
    communication_policy: dict[str, JsonValue]
    evaluation_policy: str
    risk_class: str
    content_digest: str
    supersedes_version_id: uuid.UUID | None = None
    trace_id: uuid.UUID
    created_at: datetime
    workflow_bindings: list[AgentWorkflowBindingOut] = Field(default_factory=list)
    capability_requirements: list[AgentCapabilityRequirementOut] = Field(default_factory=list)


class AgentValidationOut(ApiModel):
    validation_id: uuid.UUID
    agent_version_id: uuid.UUID
    content_digest: str
    outcome: str
    issues: list[dict[str, JsonValue]]
    registry_versions: dict[str, JsonValue]
    validator_version: str
    trace_id: uuid.UUID
    created_at: datetime


class AgentActivationRequestIn(ApiModel):
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class AgentActivationRequestOut(ApiModel):
    activation_request_id: uuid.UUID
    agent_version_id: uuid.UUID
    validation_id: uuid.UUID
    request_digest: str
    authority_summary: dict[str, JsonValue]
    trace_id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    decision: Literal["approved", "denied"] | None = None


class AgentActivationDecisionIn(ApiModel):
    decision: Literal["approved", "denied"]


class AgentInvocationIn(ApiModel):
    workflow_version_id: uuid.UUID
    query: str = Field(min_length=1, max_length=4_000)
    selected_object_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    seed_object_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class AgentInvocationOut(ApiModel):
    invocation_id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    workflow_version_id: uuid.UUID
    workflow_execution_id: uuid.UUID
    workflow_status: str
    workflow_outcome: str | None = None
    graph_revision: int
    trace_id: uuid.UUID
    created_at: datetime
    duplicate: bool = False


class AgentEvaluationIn(ApiModel):
    outcome: EvaluationOutcome
    summary: str = Field(min_length=1, max_length=2_000)
    recommendations: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class AgentEvaluationOut(ApiModel):
    evaluation_id: uuid.UUID
    invocation_id: uuid.UUID
    outcome: str
    evidence_digest: str
    summary: str
    recommendations: list[dict[str, JsonValue]]
    trace_id: uuid.UUID
    created_at: datetime


class AgentProposalIn(ApiModel):
    kind: ProposalKind
    source_kind: Literal[
        "adaptive_agent_architect",
        "adaptive_training_evaluation",
        "human",
    ]
    payload: dict[str, JsonValue]
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    agent_id: uuid.UUID | None = None
    source_invocation_id: uuid.UUID | None = None


class AgentProposalOut(ApiModel):
    proposal_id: uuid.UUID
    kind: str
    source_kind: str
    agent_id: uuid.UUID | None = None
    source_invocation_id: uuid.UUID | None = None
    payload: dict[str, JsonValue]
    payload_digest: str
    trace_id: uuid.UUID
    created_at: datetime
    decision: Literal["accepted", "rejected"] | None = None
    resulting_agent_id: uuid.UUID | None = None
    resulting_version_id: uuid.UUID | None = None


class AgentProposalDecisionIn(ApiModel):
    decision: Literal["accepted", "rejected"]


class CommunicationProfileIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    audience: Audience = Audience.GENERAL
    reading_level: ReadingLevel = ReadingLevel.STANDARD
    formality: Formality = Formality.NEUTRAL
    verbosity: Verbosity = Verbosity.BALANCED
    technical_depth: TechnicalDepth = TechnicalDepth.MEDIUM
    orwell_rules: bool = False
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class CommunicationProfileVersionIn(ApiModel):
    audience: Audience = Audience.GENERAL
    reading_level: ReadingLevel = ReadingLevel.STANDARD
    formality: Formality = Formality.NEUTRAL
    verbosity: Verbosity = Verbosity.BALANCED
    technical_depth: TechnicalDepth = TechnicalDepth.MEDIUM
    orwell_rules: bool = False
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class CommunicationProfileOut(ApiModel):
    profile_id: uuid.UUID
    profile_version_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    version_number: int
    name: str
    audience: str
    reading_level: str
    formality: str
    verbosity: str
    technical_depth: str
    orwell_rules: bool
    content_digest: str
    trace_id: uuid.UUID
    created_at: datetime


class CommunicationRevisionIn(ApiModel):
    profile_version_id: uuid.UUID
    source_invocation_id: uuid.UUID | None = None
    original_text: str = Field(min_length=1, max_length=40_000)
    revised_text: str = Field(min_length=1, max_length=40_000)
    citation_ids: list[str] = Field(default_factory=list, max_length=100)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class CommunicationRevisionOut(ApiModel):
    revision_id: uuid.UUID
    profile_version_id: uuid.UUID
    source_invocation_id: uuid.UUID | None = None
    original_text: str
    revised_text: str
    original_digest: str
    revised_digest: str
    protected_facts_digest: str
    preservation_status: str
    safe_failure_code: str | None = None
    trace_id: uuid.UUID
    created_at: datetime
    decision: Literal["accepted", "rejected"] | None = None


class CommunicationRevisionDecisionIn(ApiModel):
    decision: Literal["accepted", "rejected"]


class AgentLifecycleIn(ApiModel):
    operation: Literal["suspend", "restore", "retire"]
    reason_code: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_:-]+$",
    )


class AgentOut(ApiModel):
    agent_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    kind: str
    display_name: str
    description: str
    lifecycle_state: str
    trace_id: uuid.UUID
    created_at: datetime
    versions: list[AgentVersionOut]
    validations: list[AgentValidationOut]
    activation_requests: list[AgentActivationRequestOut]
    invocations: list[AgentInvocationOut]
    evaluations: list[AgentEvaluationOut]
    proposals: list[AgentProposalOut]
    duplicate: bool = False


class AgentRegistriesOut(ApiModel):
    registry_version: str
    agent_kinds: list[str]
    agent_lifecycles: list[str]
    agent_version_lifecycles: list[str]
    proposal_kinds: list[str]
    validation_outcomes: list[str]
    evaluation_outcomes: list[str]
    capabilities: list[str]
    resource_kinds: list[str]
    risk_classes: list[str]
    providers: dict[str, list[str]]
    communication: dict[str, list[str]]
    server_maximums: AgentLimitsIn
