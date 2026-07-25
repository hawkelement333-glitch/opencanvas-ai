from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    BoundedAgentActivationDecision,
    BoundedAgentActivationRequest,
    BoundedAgentCapabilityRequirement,
    BoundedAgentEvaluation,
    BoundedAgentIdentity,
    BoundedAgentInvocation,
    BoundedAgentLifecycleState,
    BoundedAgentProposal,
    BoundedAgentProposalDecision,
    BoundedAgentValidationReport,
    BoundedAgentVersion,
    BoundedAgentVersionState,
    BoundedAgentWorkflowBinding,
    BoundedCommunicationProfile,
    BoundedCommunicationProfileVersion,
    BoundedCommunicationRevision,
    BoundedCommunicationRevisionDecision,
    Canvas,
    ControlledWorkflowExecution,
    ControlledWorkflowStep,
    ControlledWorkflowVersion,
    ControlledWorkflowVersionState,
    Workspace,
)
from opencanvas_api.services.agents.contracts import Capability, ResourceKind, RiskClass
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import CompleteTraceInput, StartTraceInput, TraceService
from opencanvas_api.services.workflows import (
    ControlledWorkflowService,
    StartWorkflow,
    WorkflowExecutionRecord,
)

AGENT_STUDIO_SCHEMA_VERSION: Literal["bounded-agent-studio-v1"] = "bounded-agent-studio-v1"
AGENT_DEFINITION_SCHEMA_VERSION: Literal["bounded-agent-definition-v1"] = (
    "bounded-agent-definition-v1"
)
AGENT_REGISTRY_VERSION = "bounded-agent-registries-v1"
AGENT_VALIDATOR_VERSION = "bounded-agent-validator-v1"
PROMPT_TEMPLATE_VERSION = "bounded-agent-prompt-v1"
ACTIVATION_TTL = timedelta(minutes=15)


class AgentKind(StrEnum):
    WORKFLOW_ASSISTANT = "workflow_assistant"
    GROUNDED_RESEARCH_ASSISTANT = "grounded_research_assistant"
    DOCUMENT_ANALYSIS_ASSISTANT = "document_analysis_assistant"
    CONTROLLED_OPERATIONS_ASSISTANT = "controlled_operations_assistant"
    COMMUNICATION_ASSISTANT = "communication_assistant"
    EVALUATION_ASSISTANT = "evaluation_assistant"
    AGENT_DESIGN_ASSISTANT = "agent_design_assistant"


class AgentLifecycle(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"
    AWAITING_ACTIVATION_APPROVAL = "awaiting_activation_approval"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    REJECTED = "rejected"


class AgentVersionLifecycle(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"
    AWAITING_ACTIVATION_APPROVAL = "awaiting_activation_approval"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    RETIRED = "retired"


class ProposalKind(StrEnum):
    AGENT_CREATION = "agent_creation"
    AGENT_VERSION_IMPROVEMENT = "agent_version_improvement"
    WORKFLOW_BINDING = "workflow_binding"
    CAPABILITY_REQUIREMENT = "capability_requirement"
    PROVIDER_POLICY = "provider_policy"
    COMMUNICATION_REVISION = "communication_revision"
    EVALUATION_RECOMMENDATION = "evaluation_recommendation"


class ValidationOutcome(StrEnum):
    VALID = "valid"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_WORKFLOW = "invalid_workflow"
    INVALID_CAPABILITY = "invalid_capability"
    INVALID_SCOPE = "invalid_scope"
    INVALID_PROVIDER = "invalid_provider"
    INVALID_LIMITS = "invalid_limits"
    INVALID_PROMPT_CONTRACT = "invalid_prompt_contract"
    INVALID_COMMUNICATION_POLICY = "invalid_communication_policy"
    RISK_EXCEEDS_ALLOWED_BOUNDARY = "risk_exceeds_allowed_boundary"
    APPROVAL_REQUIRED = "approval_required"
    UNSUPPORTED_VERSION = "unsupported_version"


class EvaluationOutcome(StrEnum):
    MEETS_REQUIREMENTS = "meets_requirements"
    PARTIALLY_MEETS_REQUIREMENTS = "partially_meets_requirements"
    FAILS_REQUIREMENTS = "fails_requirements"
    UNSAFE_RESULT = "unsafe_result"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BOUNDED_RESULT = "bounded_result"
    EVALUATION_UNAVAILABLE = "evaluation_unavailable"


class Audience(StrEnum):
    GENERAL = "general"
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    ACADEMIC = "academic"


class ReadingLevel(StrEnum):
    PLAIN = "plain"
    STANDARD = "standard"
    ADVANCED = "advanced"


class Formality(StrEnum):
    CONVERSATIONAL = "conversational"
    NEUTRAL = "neutral"
    FORMAL = "formal"


class Verbosity(StrEnum):
    CONCISE = "concise"
    BALANCED = "balanced"
    DETAILED = "detailed"


class TechnicalDepth(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentLimits(AgentContractModel):
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


class CapabilityRequirementInput(AgentContractModel):
    capability: Capability
    resource_kind: ResourceKind


class CommunicationPolicyInput(AgentContractModel):
    profile_version_id: uuid.UUID | None = None
    require_human_acceptance: bool = True


class AgentVersionInput(AgentContractModel):
    schema_version: Literal["bounded-agent-definition-v1"] = AGENT_DEFINITION_SCHEMA_VERSION
    purpose: str = Field(min_length=1, max_length=2_000)
    system_instruction: str = Field(min_length=1, max_length=8_000)
    workflow_version_ids: tuple[uuid.UUID, ...] = Field(min_length=1, max_length=8)
    capability_requirements: tuple[CapabilityRequirementInput, ...] = Field(
        min_length=1,
        max_length=32,
    )
    selected_context_policy: Literal["required_explicit", "optional_explicit"] = "required_explicit"
    provider: Literal["mock", "openai"] = "mock"
    model: str = Field(min_length=1, max_length=160)
    limits: AgentLimits = Field(default_factory=AgentLimits)
    communication_policy: CommunicationPolicyInput = Field(default_factory=CommunicationPolicyInput)
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
    def unique_workflows(cls, value: tuple[uuid.UUID, ...]) -> tuple[uuid.UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("workflow version references must be unique")
        return value

    @field_validator("capability_requirements")
    @classmethod
    def unique_capabilities(
        cls,
        value: tuple[CapabilityRequirementInput, ...],
    ) -> tuple[CapabilityRequirementInput, ...]:
        keys = {(item.capability, item.resource_kind) for item in value}
        if len(keys) != len(value):
            raise ValueError("capability requirements must be unique")
        return value


class CommunicationProfileInput(AgentContractModel):
    audience: Audience = Audience.GENERAL
    reading_level: ReadingLevel = ReadingLevel.STANDARD
    formality: Formality = Formality.NEUTRAL
    verbosity: Verbosity = Verbosity.BALANCED
    technical_depth: TechnicalDepth = TechnicalDepth.MEDIUM
    orwell_rules: bool = False


@dataclass(frozen=True, slots=True)
class AgentRecord:
    identity: BoundedAgentIdentity
    identity_state: str
    versions: tuple[BoundedAgentVersion, ...]
    version_states: dict[uuid.UUID, str]
    validations: tuple[BoundedAgentValidationReport, ...]
    activation_requests: tuple[BoundedAgentActivationRequest, ...]
    activation_decisions: tuple[BoundedAgentActivationDecision, ...]
    invocations: tuple[BoundedAgentInvocation, ...]
    evaluations: tuple[BoundedAgentEvaluation, ...]
    proposals: tuple[BoundedAgentProposal, ...]
    duplicate: bool = False


class AgentStudioError(RuntimeError):
    code = "agent_studio_failed"
    safe_message = "The Agent Studio operation could not be completed."


class AgentStudioValidationError(AgentStudioError):
    code = "agent_studio_invalid"
    safe_message = "The Agent Studio request is invalid."


class AgentStudioNotFoundError(AgentStudioError):
    code = "agent_studio_not_found"
    safe_message = "The requested Agent Studio record was not found."


class AgentStudioConflictError(AgentStudioError):
    code = "agent_studio_conflict"
    safe_message = "The Agent Studio record changed or conflicts with existing evidence."


class AgentStudioAuthorityError(AgentStudioError):
    code = "agent_studio_authority_denied"
    safe_message = "The requested Agent Studio action is not authorized."


class AgentStudioStorageError(AgentStudioError):
    code = "agent_studio_storage_failed"
    safe_message = "Agent Studio persistence is temporarily unavailable."


_PROVIDER_MODELS = {
    "mock": frozenset({"mock-context-v1"}),
    "openai": frozenset({"gpt-5.6-terra"}),
}
_FORBIDDEN_PROMPT_PATTERNS = (
    re.compile(r"\b(?:you|agent)\s+(?:may|must|should)\s+(?:self-)?activate\b", re.I),
    re.compile(r"\b(?:you|agent)\s+(?:may|must|should)\s+(?:self-)?approve\b", re.I),
    re.compile(r"\bgrant\s+(?:yourself|authority|capabilit(?:y|ies))\b", re.I),
    re.compile(r"\b(?:run|execute)\s+(?:arbitrary\s+)?(?:shell|sql|code|http)\b", re.I),
    re.compile(r"\binstall\s+(?:a\s+)?(?:plugin|tool|mcp)\b", re.I),
    re.compile(r"\b(?:academy|quarantine|rehabilitation|tribunal)\s+(?:system|authority)\b", re.I),
)
_NUMBER_OR_DATE = re.compile(
    r"\b(?:\d{1,4}(?:[-/.]\d{1,2}){1,2}|\d+(?:\.\d+)?%?|"
    r"\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds?|minutes?|hours?|days?|kg|g|km|m|cm|mm))\b",
    re.I,
)
_URL = re.compile(r"https?://[^\s<>()]+", re.I)
_HASH = re.compile(r"\b[0-9a-f]{32,64}\b", re.I)
_QUOTE = re.compile(r'"[^"\n]{1,1000}"|“[^”\n]{1,1000}”')
_NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b")
_PROTECTED_WARNINGS = (
    "insufficient evidence",
    "bounded result",
    "conflicting evidence",
    "contradiction",
    "effect committed",
    "compensation failed",
    "compensated",
    "canceled",
)


class BoundedAgentStudioService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        workflow_service: ControlledWorkflowService,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.workflow_service = workflow_service
        self.trace = TraceService(session)
        self.events = DomainEventService(session)
        self.now = _utc(now or datetime.now(UTC))

    async def create_agent(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        kind: AgentKind,
        display_name: str,
        description: str,
        version: AgentVersionInput,
        idempotency_key: str,
    ) -> AgentRecord:
        await self._authorize_operation(
            "agent.create",
            user_id,
            workspace_id,
            canvas_id,
        )
        self._idempotency(idempotency_key)
        name = _bounded_text(display_name, 160)
        safe_description = _bounded_text(description, 1_000)
        normalized_version = self._normalize_version(version)
        request_digest = _digest(
            {
                "schemaVersion": AGENT_STUDIO_SCHEMA_VERSION,
                "userId": str(user_id),
                "workspaceId": str(workspace_id),
                "canvasId": str(canvas_id),
                "kind": kind.value,
                "displayName": name,
                "description": safe_description,
                "version": normalized_version,
            }
        )
        existing = await self.session.scalar(
            select(BoundedAgentIdentity).where(
                BoundedAgentIdentity.user_id == user_id,
                BoundedAgentIdentity.workspace_id == workspace_id,
                BoundedAgentIdentity.canvas_id == canvas_id,
                BoundedAgentIdentity.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AgentStudioConflictError()
            return await self.get_agent(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                agent_id=existing.agent_id,
                duplicate=True,
            )
        await self._assert_version_references(
            user_id,
            workspace_id,
            canvas_id,
            version,
            require_active=False,
        )
        agent_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:bounded-agent:{user_id}:{workspace_id}:{canvas_id}:{idempotency_key}",
        )
        trace_id = uuid.uuid5(agent_id, "trace")
        try:
            async with self.session.begin_nested():
                await self.trace.start_trace(
                    StartTraceInput(
                        trace_id=trace_id,
                        event_type="agent.definition",
                        actor_id=str(user_id),
                        actor_type="user",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        object_id=agent_id,
                        object_type="agent_identity",
                        operation="agent.identity.create",
                        metadata={"agentKind": kind.value},
                    )
                )
                identity = BoundedAgentIdentity(
                    agent_id=agent_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    schema_version=AGENT_STUDIO_SCHEMA_VERSION,
                    kind=kind.value,
                    display_name=name,
                    description=safe_description,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    created_by_user_id=user_id,
                    trace_id=trace_id,
                    created_at=self.now,
                )
                self.session.add(identity)
                await self.session.flush()
                await self._agent_state(identity, AgentLifecycle.DRAFT, trace_id=trace_id)
                created_version = await self._persist_version(
                    identity,
                    version,
                    idempotency_key=f"initial:{idempotency_key}",
                    initial_state=AgentVersionLifecycle.DRAFT,
                )
                await self._event(
                    "agent.identity.created",
                    identity.agent_id,
                    identity,
                    trace_id,
                    related_id=created_version.version_id,
                    payload={
                        "agentId": str(identity.agent_id),
                        "agentKind": identity.kind,
                        "lifecycleState": "draft",
                    },
                )
                await self.trace.complete_trace(
                    CompleteTraceInput(
                        trace_id=trace_id,
                        event_type="agent.definition",
                        actor_id=str(user_id),
                        actor_type="user",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        object_id=agent_id,
                        object_type="agent_identity",
                        operation="agent.identity.create",
                        metadata={
                            "agentVersionId": str(created_version.version_id),
                            "definitionDigest": created_version.content_digest,
                        },
                    )
                )
        except AgentStudioError:
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return await self.get_agent(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            agent_id=agent_id,
        )

    async def create_version(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        agent_id: uuid.UUID,
        version: AgentVersionInput,
        idempotency_key: str,
    ) -> AgentRecord:
        await self._authorize_operation(
            "agent.version.create",
            user_id,
            workspace_id,
            canvas_id,
        )
        identity = await self._owned_agent(user_id, workspace_id, canvas_id, agent_id)
        if await self._agent_lifecycle(agent_id) is AgentLifecycle.RETIRED:
            raise AgentStudioConflictError()
        self._idempotency(idempotency_key)
        await self._assert_version_references(
            user_id,
            workspace_id,
            canvas_id,
            version,
            require_active=False,
        )
        normalized = self._normalize_version(version)
        digest = _digest(normalized)
        existing = await self.session.scalar(
            select(BoundedAgentVersion).where(
                BoundedAgentVersion.agent_id == agent_id,
                BoundedAgentVersion.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.content_digest != digest:
                raise AgentStudioConflictError()
            return await self.get_agent(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                agent_id=agent_id,
                duplicate=True,
            )
        try:
            async with self.session.begin_nested():
                await self._persist_version(
                    identity,
                    version,
                    idempotency_key=idempotency_key,
                    initial_state=AgentVersionLifecycle.DRAFT,
                )
        except AgentStudioError:
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return await self.get_agent(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            agent_id=agent_id,
        )

    async def validate_version(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> BoundedAgentValidationReport:
        await self._authorize_operation(
            "agent.version.validate",
            user_id,
            workspace_id,
            canvas_id,
        )
        version = await self._owned_version(user_id, workspace_id, canvas_id, version_id)
        existing = await self.session.scalar(
            select(BoundedAgentValidationReport).where(
                BoundedAgentValidationReport.agent_version_id == version_id,
                BoundedAgentValidationReport.content_digest == version.content_digest,
            )
        )
        if existing is not None:
            return existing
        if _digest(version.normalized_definition) != version.content_digest:
            raise AgentStudioConflictError()
        issues: list[dict[str, object]] = []
        outcome = ValidationOutcome.VALID
        definition = AgentVersionInput.model_validate(version.normalized_definition)
        try:
            await self._assert_version_references(
                user_id,
                workspace_id,
                canvas_id,
                definition,
                require_active=True,
            )
        except AgentStudioNotFoundError:
            outcome = ValidationOutcome.INVALID_WORKFLOW
            issues.append({"code": "workflow_unavailable"})
        except AgentStudioAuthorityError:
            outcome = ValidationOutcome.INVALID_SCOPE
            issues.append({"code": "workflow_scope_invalid"})
        if outcome is ValidationOutcome.VALID:
            workflow_capabilities = set(
                (
                    await self.session.scalars(
                        select(ControlledWorkflowStep.capability).where(
                            ControlledWorkflowStep.version_id.in_(definition.workflow_version_ids)
                        )
                    )
                ).all()
            )
            declared = {item.capability.value for item in definition.capability_requirements}
            if not workflow_capabilities.issubset(declared):
                outcome = ValidationOutcome.INVALID_CAPABILITY
                issues.append({"code": "workflow_capability_missing"})
        if definition.model not in _PROVIDER_MODELS[definition.provider]:
            outcome = ValidationOutcome.INVALID_PROVIDER
            issues.append({"code": "provider_model_not_allowlisted"})
        if any(
            pattern.search(definition.system_instruction) for pattern in _FORBIDDEN_PROMPT_PATTERNS
        ):
            outcome = ValidationOutcome.INVALID_PROMPT_CONTRACT
            issues.append({"code": "prompt_requests_prohibited_authority"})
        if definition.risk_class is RiskClass.R4_PROHIBITED:
            outcome = ValidationOutcome.RISK_EXCEEDS_ALLOWED_BOUNDARY
            issues.append({"code": "prohibited_risk"})
        profile_version_id = definition.communication_policy.profile_version_id
        if profile_version_id is not None:
            profile = await self.session.scalar(
                select(BoundedCommunicationProfileVersion).where(
                    BoundedCommunicationProfileVersion.profile_version_id == profile_version_id,
                    BoundedCommunicationProfileVersion.user_id == user_id,
                    BoundedCommunicationProfileVersion.workspace_id == workspace_id,
                )
            )
            if profile is None:
                outcome = ValidationOutcome.INVALID_COMMUNICATION_POLICY
                issues.append({"code": "communication_profile_unavailable"})
        trace_id = uuid.uuid5(version.version_id, f"validation:{version.content_digest}")
        report = BoundedAgentValidationReport(
            validation_id=uuid.uuid5(trace_id, "report"),
            agent_version_id=version.version_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            content_digest=version.content_digest,
            outcome=outcome.value,
            issues=issues,
            registry_versions={
                "agentRegistry": AGENT_REGISTRY_VERSION,
                "capabilityRegistry": "controlled-agent-v1",
                "workflowRegistry": "controlled-workflow-v1",
                "providerRegistry": "ai-provider-v1",
            },
            validator_version=AGENT_VALIDATOR_VERSION,
            trace_id=trace_id,
            created_at=self.now,
        )
        try:
            async with self.session.begin_nested():
                await self.trace.start_trace(
                    StartTraceInput(
                        trace_id=trace_id,
                        parent_trace_id=version.trace_id,
                        event_type="agent.validation",
                        actor_id=str(user_id),
                        actor_type="user",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        object_id=report.validation_id,
                        object_type="agent_validation",
                        operation="agent.version.validate",
                        metadata={
                            "agentVersionId": str(version_id),
                            "definitionDigest": version.content_digest,
                        },
                    )
                )
                self.session.add(report)
                await self.session.flush()
                state = (
                    AgentVersionLifecycle.VALIDATED
                    if outcome is ValidationOutcome.VALID
                    else AgentVersionLifecycle.VALIDATION_FAILED
                )
                await self._version_state(version, state, trace_id=trace_id)
                identity = await self._owned_agent(
                    user_id,
                    workspace_id,
                    canvas_id,
                    version.agent_id,
                )
                await self._agent_state(
                    identity,
                    (
                        AgentLifecycle.VALIDATED
                        if outcome is ValidationOutcome.VALID
                        else AgentLifecycle.VALIDATION_FAILED
                    ),
                    trace_id=trace_id,
                )
                event_type = (
                    "agent.version.validated"
                    if outcome is ValidationOutcome.VALID
                    else "agent.version.validation_failed"
                )
                await self._event(
                    event_type,
                    version.version_id,
                    identity,
                    trace_id,
                    related_id=report.validation_id,
                    payload={
                        "agentId": str(identity.agent_id),
                        "agentVersionId": str(version.version_id),
                        "versionNumber": version.version_number,
                        "validationOutcome": outcome.value,
                    },
                )
                await self.trace.complete_trace(
                    CompleteTraceInput(
                        trace_id=trace_id,
                        parent_trace_id=version.trace_id,
                        event_type="agent.validation",
                        actor_id=str(user_id),
                        actor_type="user",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        object_id=report.validation_id,
                        object_type="agent_validation",
                        operation="agent.version.validate",
                        metadata={"validationOutcome": outcome.value},
                    )
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return report

    async def request_activation(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        version_id: uuid.UUID,
        idempotency_key: str,
    ) -> BoundedAgentActivationRequest:
        await self._authorize_operation(
            "agent.activation.request",
            user_id,
            workspace_id,
            canvas_id,
        )
        self._idempotency(idempotency_key)
        version = await self._owned_version(user_id, workspace_id, canvas_id, version_id)
        if await self._version_lifecycle(version_id) is not AgentVersionLifecycle.VALIDATED:
            raise AgentStudioConflictError()
        validation = await self.session.scalar(
            select(BoundedAgentValidationReport)
            .where(
                BoundedAgentValidationReport.agent_version_id == version_id,
                BoundedAgentValidationReport.content_digest == version.content_digest,
                BoundedAgentValidationReport.outcome == ValidationOutcome.VALID.value,
            )
            .order_by(BoundedAgentValidationReport.created_at.desc())
            .limit(1)
        )
        if validation is None:
            raise AgentStudioAuthorityError()
        bindings = await self._bindings(version_id)
        requirements = await self._requirements(version_id)
        authority_summary: dict[str, object] = {
            "agentVersionId": str(version_id),
            "definitionDigest": version.content_digest,
            "workflowVersions": [
                {
                    "workflowVersionId": str(item.workflow_version_id),
                    "workflowDigest": item.workflow_digest,
                }
                for item in bindings
            ],
            "capabilityRequirements": [
                {
                    "capability": item.capability,
                    "resourceKind": item.resource_kind,
                }
                for item in requirements
            ],
            "scope": {
                "userId": str(user_id),
                "workspaceId": str(workspace_id),
                "canvasId": str(canvas_id),
            },
            "provider": version.provider,
            "model": version.model,
            "riskClass": version.risk_class,
            "limits": version.limits,
            "grantsCreated": False,
        }
        request_digest = _digest(authority_summary)
        existing = await self.session.scalar(
            select(BoundedAgentActivationRequest).where(
                BoundedAgentActivationRequest.agent_version_id == version_id,
                BoundedAgentActivationRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AgentStudioConflictError()
            return existing
        identity = await self._owned_agent(
            user_id,
            workspace_id,
            canvas_id,
            version.agent_id,
        )
        request_id = uuid.uuid5(version_id, f"activation:{idempotency_key}")
        trace_id = uuid.uuid5(request_id, "trace")
        row = BoundedAgentActivationRequest(
            activation_request_id=request_id,
            agent_version_id=version_id,
            validation_id=validation.validation_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            authority_summary=authority_summary,
            requested_by_user_id=user_id,
            trace_id=trace_id,
            created_at=self.now,
            expires_at=self.now + ACTIVATION_TTL,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                await self._version_state(
                    version,
                    AgentVersionLifecycle.AWAITING_ACTIVATION_APPROVAL,
                    trace_id=trace_id,
                )
                await self._agent_state(
                    identity,
                    AgentLifecycle.AWAITING_ACTIVATION_APPROVAL,
                    trace_id=trace_id,
                )
                await self._event(
                    "agent.activation.requested",
                    row.activation_request_id,
                    identity,
                    trace_id,
                    related_id=version_id,
                    payload={
                        "agentId": str(identity.agent_id),
                        "agentVersionId": str(version_id),
                        "lifecycleState": "awaiting_activation_approval",
                    },
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def decide_activation(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        activation_request_id: uuid.UUID,
        decision: Literal["approved", "denied"],
        session_id: uuid.UUID,
    ) -> BoundedAgentActivationDecision:
        await self._authorize_operation(
            "agent.activation.decide",
            user_id,
            workspace_id,
            canvas_id,
        )
        request = await self.session.scalar(
            select(BoundedAgentActivationRequest).where(
                BoundedAgentActivationRequest.activation_request_id == activation_request_id,
                BoundedAgentActivationRequest.user_id == user_id,
                BoundedAgentActivationRequest.workspace_id == workspace_id,
                BoundedAgentActivationRequest.canvas_id == canvas_id,
            )
        )
        if request is None:
            raise AgentStudioNotFoundError()
        existing = await self.session.scalar(
            select(BoundedAgentActivationDecision).where(
                BoundedAgentActivationDecision.activation_request_id == activation_request_id
            )
        )
        if existing is not None:
            if existing.decision != decision or existing.decided_by_user_id != user_id:
                raise AgentStudioConflictError()
            return existing
        if _utc(request.expires_at) <= self.now:
            raise AgentStudioAuthorityError()
        version = await self._owned_version(
            user_id,
            workspace_id,
            canvas_id,
            request.agent_version_id,
        )
        if version.content_digest != request.authority_summary.get("definitionDigest"):
            raise AgentStudioAuthorityError()
        if (
            await self._version_lifecycle(version.version_id)
            is not AgentVersionLifecycle.AWAITING_ACTIVATION_APPROVAL
        ):
            raise AgentStudioConflictError()
        await self._assert_persisted_bindings(version, require_active=True)
        identity = await self._owned_agent(
            user_id,
            workspace_id,
            canvas_id,
            version.agent_id,
        )
        trace_id = request.trace_id
        row = BoundedAgentActivationDecision(
            activation_decision_id=uuid.uuid5(request.activation_request_id, decision),
            activation_request_id=request.activation_request_id,
            agent_version_id=version.version_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            decision=decision,
            request_digest=request.request_digest,
            decided_by_user_id=user_id,
            session_id=session_id,
            trace_id=trace_id,
            decided_at=self.now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                if decision == "denied":
                    await self._version_state(
                        version,
                        AgentVersionLifecycle.REJECTED,
                        trace_id=trace_id,
                        reason_code="activation_denied",
                    )
                    await self._agent_state(
                        identity,
                        AgentLifecycle.REJECTED,
                        trace_id=trace_id,
                        reason_code="activation_denied",
                    )
                else:
                    active = await self._active_version(identity.agent_id)
                    if active is not None and active.version_id != version.version_id:
                        await self._version_state(
                            active,
                            AgentVersionLifecycle.SUPERSEDED,
                            trace_id=trace_id,
                            reason_code="new_agent_version_activated",
                        )
                    await self._version_state(
                        version,
                        AgentVersionLifecycle.APPROVED,
                        trace_id=trace_id,
                    )
                    await self._version_state(
                        version,
                        AgentVersionLifecycle.ACTIVE,
                        trace_id=trace_id,
                    )
                    await self._agent_state(
                        identity,
                        AgentLifecycle.ACTIVE,
                        trace_id=trace_id,
                    )
                    await self._event(
                        "agent.version.activated",
                        version.version_id,
                        identity,
                        trace_id,
                        related_id=request.activation_request_id,
                        payload={
                            "agentId": str(identity.agent_id),
                            "agentVersionId": str(version.version_id),
                            "versionNumber": version.version_number,
                            "lifecycleState": "active",
                        },
                    )
                await self._event(
                    (
                        "agent.activation.approved"
                        if decision == "approved"
                        else "agent.activation.denied"
                    ),
                    request.activation_request_id,
                    identity,
                    trace_id,
                    related_id=version.version_id,
                    payload={
                        "agentId": str(identity.agent_id),
                        "agentVersionId": str(version.version_id),
                        "activationDecision": decision,
                    },
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def invoke(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        agent_id: uuid.UUID,
        workflow_version_id: uuid.UUID,
        query: str,
        selected_object_ids: tuple[uuid.UUID, ...],
        seed_object_ids: tuple[uuid.UUID, ...],
        idempotency_key: str,
    ) -> tuple[BoundedAgentInvocation, WorkflowExecutionRecord]:
        await self._authorize_operation(
            "agent.invoke",
            user_id,
            workspace_id,
            canvas_id,
        )
        self._idempotency(idempotency_key)
        identity = await self._owned_agent(user_id, workspace_id, canvas_id, agent_id)
        if await self._agent_lifecycle(agent_id) is not AgentLifecycle.ACTIVE:
            raise AgentStudioAuthorityError()
        version = await self._active_version(agent_id)
        if version is None:
            raise AgentStudioAuthorityError()
        if _digest(version.normalized_definition) != version.content_digest:
            raise AgentStudioConflictError()
        activation = await self.session.scalar(
            select(BoundedAgentActivationDecision)
            .where(
                BoundedAgentActivationDecision.agent_version_id == version.version_id,
                BoundedAgentActivationDecision.decision == "approved",
                BoundedAgentActivationDecision.request_digest
                == BoundedAgentActivationRequest.request_digest,
            )
            .join(
                BoundedAgentActivationRequest,
                BoundedAgentActivationRequest.activation_request_id
                == BoundedAgentActivationDecision.activation_request_id,
            )
            .order_by(BoundedAgentActivationDecision.decided_at.desc())
            .limit(1)
        )
        if activation is None:
            raise AgentStudioAuthorityError()
        bindings = await self._bindings(version.version_id)
        binding = next(
            (item for item in bindings if item.workflow_version_id == workflow_version_id),
            None,
        )
        if binding is None:
            raise AgentStudioAuthorityError()
        await self._assert_persisted_bindings(version, require_active=True)
        normalized_query = " ".join(query.split())
        selected = tuple(dict.fromkeys(selected_object_ids))
        seeds = tuple(dict.fromkeys(seed_object_ids))
        request_digest = _digest(
            {
                "agentId": str(agent_id),
                "agentVersionId": str(version.version_id),
                "definitionDigest": version.content_digest,
                "workflowVersionId": str(workflow_version_id),
                "workflowDigest": binding.workflow_digest,
                "query": normalized_query,
                "selectedObjectIds": [str(value) for value in selected],
                "seedObjectIds": [str(value) for value in seeds],
            }
        )
        existing = await self.session.scalar(
            select(BoundedAgentInvocation).where(
                BoundedAgentInvocation.user_id == user_id,
                BoundedAgentInvocation.workspace_id == workspace_id,
                BoundedAgentInvocation.canvas_id == canvas_id,
                BoundedAgentInvocation.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AgentStudioConflictError()
            workflow = await self.workflow_service.get_execution(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                execution_id=existing.workflow_execution_id,
                duplicate=True,
            )
            return existing, workflow
        workflow_key = f"agent-{hashlib.sha256(idempotency_key.encode()).hexdigest()}"
        workflow = await self.workflow_service.start(
            StartWorkflow(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                version_id=workflow_version_id,
                query=normalized_query,
                selected_object_ids=selected,
                seed_object_ids=seeds,
                idempotency_key=workflow_key,
            )
        )
        invocation_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:agent-invocation:{user_id}:{workspace_id}:{canvas_id}:{idempotency_key}",
        )
        trace_id = uuid.uuid5(invocation_id, "trace")
        row = BoundedAgentInvocation(
            invocation_id=invocation_id,
            agent_id=agent_id,
            agent_version_id=version.version_id,
            workflow_version_id=workflow_version_id,
            workflow_execution_id=workflow.execution.execution_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            selected_object_ids=[str(value) for value in selected],
            graph_revision=workflow.execution.graph_revision,
            trace_id=trace_id,
            created_at=self.now,
        )
        try:
            async with self.session.begin_nested():
                await self.trace.start_trace(
                    StartTraceInput(
                        trace_id=trace_id,
                        parent_trace_id=version.trace_id,
                        event_type="agent.invocation",
                        actor_id=str(user_id),
                        actor_type="user",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        object_id=invocation_id,
                        object_type="agent_invocation",
                        operation="agent.invocation.start",
                        metadata={
                            "agentId": str(agent_id),
                            "agentVersionId": str(version.version_id),
                            "definitionDigest": version.content_digest,
                            "workflowExecutionId": str(workflow.execution.execution_id),
                            "workflowTraceId": str(workflow.execution.trace_id),
                            "graphRevision": workflow.execution.graph_revision,
                        },
                    )
                )
                self.session.add(row)
                await self.session.flush()
                await self._event(
                    "agent.invocation.started",
                    invocation_id,
                    identity,
                    trace_id,
                    related_id=workflow.execution.execution_id,
                    payload={
                        "agentId": str(agent_id),
                        "agentVersionId": str(version.version_id),
                        "workflowVersionId": str(workflow_version_id),
                        "workflowExecutionId": str(workflow.execution.execution_id),
                    },
                )
                await self.trace.complete_trace(
                    CompleteTraceInput(
                        trace_id=trace_id,
                        parent_trace_id=version.trace_id,
                        event_type="agent.invocation",
                        actor_id=str(user_id),
                        actor_type="user",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        object_id=invocation_id,
                        object_type="agent_invocation",
                        operation="agent.invocation.start",
                        metadata={
                            "workflowExecutionId": str(workflow.execution.execution_id),
                            "workflowStatus": workflow.execution.status,
                        },
                    )
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row, workflow

    async def evaluate(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        invocation_id: uuid.UUID,
        outcome: EvaluationOutcome,
        summary: str,
        recommendations: list[dict[str, object]],
        idempotency_key: str,
    ) -> BoundedAgentEvaluation:
        await self._authorize_operation(
            "agent.evaluate",
            user_id,
            workspace_id,
            canvas_id,
        )
        self._idempotency(idempotency_key)
        invocation = await self._owned_invocation(
            user_id,
            workspace_id,
            canvas_id,
            invocation_id,
        )
        execution = await self.session.scalar(
            select(ControlledWorkflowExecution).where(
                ControlledWorkflowExecution.execution_id == invocation.workflow_execution_id,
                ControlledWorkflowExecution.user_id == user_id,
                ControlledWorkflowExecution.workspace_id == workspace_id,
                ControlledWorkflowExecution.canvas_id == canvas_id,
            )
        )
        if execution is None or execution.status not in {
            "completed",
            "failed",
            "canceled",
            "compensated",
            "compensation_failed",
        }:
            raise AgentStudioConflictError()
        evidence_digest = _digest(
            {
                "invocationId": str(invocation_id),
                "requestDigest": invocation.request_digest,
                "workflowExecutionId": str(execution.execution_id),
                "workflowStatus": execution.status,
                "workflowOutcome": execution.outcome,
                "workflowOutputDigest": execution.output_digest,
                "workflowTraceId": str(execution.trace_id),
            }
        )
        existing = await self.session.scalar(
            select(BoundedAgentEvaluation).where(
                BoundedAgentEvaluation.invocation_id == invocation_id,
                BoundedAgentEvaluation.idempotency_key == idempotency_key,
            )
        )
        normalized_summary = _bounded_text(summary, 2_000)
        safe_recommendations = _safe_recommendations(recommendations)
        if existing is not None:
            if (
                existing.evidence_digest != evidence_digest
                or existing.outcome != outcome.value
                or existing.summary != normalized_summary
            ):
                raise AgentStudioConflictError()
            return existing
        evaluation_id = uuid.uuid5(invocation_id, f"evaluation:{idempotency_key}")
        trace_id = uuid.uuid5(evaluation_id, "trace")
        row = BoundedAgentEvaluation(
            evaluation_id=evaluation_id,
            invocation_id=invocation_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            outcome=outcome.value,
            evidence_digest=evidence_digest,
            summary=normalized_summary,
            recommendations=safe_recommendations,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            created_by_user_id=user_id,
            created_at=self.now,
        )
        identity = await self._owned_agent(
            user_id,
            workspace_id,
            canvas_id,
            invocation.agent_id,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                await self._event(
                    "agent.evaluation.recorded",
                    evaluation_id,
                    identity,
                    trace_id,
                    related_id=invocation_id,
                    payload={
                        "agentId": str(invocation.agent_id),
                        "agentVersionId": str(invocation.agent_version_id),
                        "evaluationOutcome": outcome.value,
                    },
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def create_proposal(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        kind: ProposalKind,
        source_kind: Literal[
            "adaptive_agent_architect",
            "adaptive_training_evaluation",
            "human",
        ],
        payload: dict[str, object],
        idempotency_key: str,
        agent_id: uuid.UUID | None = None,
        source_invocation_id: uuid.UUID | None = None,
    ) -> BoundedAgentProposal:
        await self._authorize_operation(
            "agent.proposal.create",
            user_id,
            workspace_id,
            canvas_id,
        )
        self._idempotency(idempotency_key)
        if agent_id is not None:
            await self._owned_agent(user_id, workspace_id, canvas_id, agent_id)
        if source_invocation_id is not None:
            await self._owned_invocation(
                user_id,
                workspace_id,
                canvas_id,
                source_invocation_id,
            )
        safe_payload = _json_object(payload)
        if kind in {
            ProposalKind.AGENT_CREATION,
            ProposalKind.AGENT_VERSION_IMPROVEMENT,
        }:
            self._proposal_definition(safe_payload)
        payload_digest = _digest(safe_payload)
        request_digest = _digest(
            {
                "kind": kind.value,
                "sourceKind": source_kind,
                "agentId": str(agent_id) if agent_id else None,
                "sourceInvocationId": (str(source_invocation_id) if source_invocation_id else None),
                "payloadDigest": payload_digest,
            }
        )
        existing = await self.session.scalar(
            select(BoundedAgentProposal).where(
                BoundedAgentProposal.user_id == user_id,
                BoundedAgentProposal.workspace_id == workspace_id,
                BoundedAgentProposal.canvas_id == canvas_id,
                BoundedAgentProposal.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AgentStudioConflictError()
            return existing
        proposal_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:agent-proposal:{user_id}:{workspace_id}:{canvas_id}:{idempotency_key}",
        )
        trace_id = uuid.uuid5(proposal_id, "trace")
        row = BoundedAgentProposal(
            proposal_id=proposal_id,
            agent_id=agent_id,
            source_invocation_id=source_invocation_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            kind=kind.value,
            source_kind=source_kind,
            payload=safe_payload,
            payload_digest=payload_digest,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            created_at=self.now,
        )
        subject = (
            await self._owned_agent(user_id, workspace_id, canvas_id, agent_id)
            if agent_id is not None
            else None
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                await self.events.record(
                    CreateDomainEvent(
                        event_type="agent.proposal.created",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        canvas_id=canvas_id,
                        subject_id=proposal_id,
                        actor_user_id=user_id,
                        source_identity=f"agent-proposal:{proposal_id}:created",
                        trace_id=trace_id,
                        payload={
                            "agentId": (str(subject.agent_id) if subject is not None else None),
                            "proposalKind": kind.value,
                        },
                        origin_type="authenticated_user",
                        related_id=agent_id,
                    )
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def decide_proposal(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        proposal_id: uuid.UUID,
        decision: Literal["accepted", "rejected"],
    ) -> BoundedAgentProposalDecision:
        await self._authorize_operation(
            "agent.proposal.decide",
            user_id,
            workspace_id,
            canvas_id,
        )
        proposal = await self._owned_proposal(
            user_id,
            workspace_id,
            canvas_id,
            proposal_id,
        )
        existing = await self.session.scalar(
            select(BoundedAgentProposalDecision).where(
                BoundedAgentProposalDecision.proposal_id == proposal_id
            )
        )
        if existing is not None:
            if existing.decision != decision:
                raise AgentStudioConflictError()
            return existing
        resulting_agent_id: uuid.UUID | None = None
        resulting_version_id: uuid.UUID | None = None
        if decision == "accepted" and proposal.kind in {
            ProposalKind.AGENT_CREATION.value,
            ProposalKind.AGENT_VERSION_IMPROVEMENT.value,
        }:
            kind, name, description, version = self._proposal_definition(proposal.payload)
            if proposal.kind == ProposalKind.AGENT_CREATION.value:
                record = await self.create_agent(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    kind=kind,
                    display_name=name,
                    description=description,
                    version=version,
                    idempotency_key=f"proposal-{proposal_id}",
                )
                resulting_agent_id = record.identity.agent_id
                resulting_version_id = record.versions[-1].version_id
            else:
                if proposal.agent_id is None:
                    raise AgentStudioValidationError()
                record = await self.create_version(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    agent_id=proposal.agent_id,
                    version=version,
                    idempotency_key=f"proposal-{proposal_id}",
                )
                resulting_agent_id = proposal.agent_id
                resulting_version_id = record.versions[-1].version_id
        row = BoundedAgentProposalDecision(
            decision_id=uuid.uuid5(proposal_id, decision),
            proposal_id=proposal_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            decision=decision,
            decided_by_user_id=user_id,
            resulting_agent_id=resulting_agent_id,
            resulting_version_id=resulting_version_id,
            trace_id=proposal.trace_id,
            decided_at=self.now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                await self.events.record(
                    CreateDomainEvent(
                        event_type=(
                            "agent.proposal.accepted"
                            if decision == "accepted"
                            else "agent.proposal.rejected"
                        ),
                        user_id=user_id,
                        workspace_id=workspace_id,
                        canvas_id=canvas_id,
                        subject_id=proposal_id,
                        actor_user_id=user_id,
                        source_identity=f"agent-proposal:{proposal_id}:{decision}",
                        trace_id=proposal.trace_id,
                        payload={
                            "agentId": (str(proposal.agent_id) if proposal.agent_id else None),
                            "proposalKind": proposal.kind,
                            "decision": decision,
                        },
                        origin_type="authenticated_user",
                        related_id=resulting_version_id or resulting_agent_id,
                    )
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def create_communication_profile(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        name: str,
        profile: CommunicationProfileInput,
        idempotency_key: str,
    ) -> tuple[BoundedCommunicationProfile, BoundedCommunicationProfileVersion]:
        await self._authorize_operation(
            "communication_profile.create",
            user_id,
            workspace_id,
            canvas_id,
        )
        self._idempotency(idempotency_key)
        safe_name = _bounded_text(name, 120)
        normalized = profile.model_dump(mode="json")
        request_digest = _digest({"name": safe_name, "profile": normalized})
        existing = await self.session.scalar(
            select(BoundedCommunicationProfile).where(
                BoundedCommunicationProfile.user_id == user_id,
                BoundedCommunicationProfile.workspace_id == workspace_id,
                BoundedCommunicationProfile.canvas_id == canvas_id,
                BoundedCommunicationProfile.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AgentStudioConflictError()
            version = await self.session.scalar(
                select(BoundedCommunicationProfileVersion)
                .where(BoundedCommunicationProfileVersion.profile_id == existing.profile_id)
                .order_by(BoundedCommunicationProfileVersion.version_number.desc())
                .limit(1)
            )
            if version is None:
                raise AgentStudioConflictError()
            return existing, version
        profile_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:communication-profile:{user_id}:{workspace_id}:{canvas_id}:{idempotency_key}",
        )
        trace_id = uuid.uuid5(profile_id, "trace")
        identity = BoundedCommunicationProfile(
            profile_id=profile_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            name=safe_name,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            created_by_user_id=user_id,
            trace_id=trace_id,
            created_at=self.now,
        )
        version = self._profile_version(
            identity,
            profile,
            version_number=1,
            idempotency_key=f"initial:{idempotency_key}",
        )
        try:
            async with self.session.begin_nested():
                self.session.add(identity)
                self.session.add(version)
                await self.session.flush()
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return identity, version

    async def create_profile_version(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        profile_id: uuid.UUID,
        profile: CommunicationProfileInput,
        idempotency_key: str,
    ) -> BoundedCommunicationProfileVersion:
        self._idempotency(idempotency_key)
        await self._authorize_operation(
            "communication_profile.version.create",
            user_id,
            workspace_id,
            canvas_id,
        )
        identity = await self.session.scalar(
            select(BoundedCommunicationProfile).where(
                BoundedCommunicationProfile.profile_id == profile_id,
                BoundedCommunicationProfile.user_id == user_id,
                BoundedCommunicationProfile.workspace_id == workspace_id,
                BoundedCommunicationProfile.canvas_id == canvas_id,
            )
        )
        if identity is None:
            raise AgentStudioNotFoundError()
        digest = _digest(profile.model_dump(mode="json"))
        existing = await self.session.scalar(
            select(BoundedCommunicationProfileVersion).where(
                BoundedCommunicationProfileVersion.profile_id == profile_id,
                BoundedCommunicationProfileVersion.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.content_digest != digest:
                raise AgentStudioConflictError()
            return existing
        count = (
            await self.session.scalar(
                select(func.count())
                .select_from(BoundedCommunicationProfileVersion)
                .where(BoundedCommunicationProfileVersion.profile_id == profile_id)
            )
            or 0
        )
        row = self._profile_version(
            identity,
            profile,
            version_number=count + 1,
            idempotency_key=idempotency_key,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def propose_communication_revision(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        profile_version_id: uuid.UUID,
        original_text: str,
        revised_text: str,
        citation_ids: tuple[str, ...],
        idempotency_key: str,
        source_invocation_id: uuid.UUID | None = None,
    ) -> BoundedCommunicationRevision:
        await self._authorize_operation(
            "communication_revision.propose",
            user_id,
            workspace_id,
            canvas_id,
        )
        self._idempotency(idempotency_key)
        profile = await self.session.scalar(
            select(BoundedCommunicationProfileVersion).where(
                BoundedCommunicationProfileVersion.profile_version_id == profile_version_id,
                BoundedCommunicationProfileVersion.user_id == user_id,
                BoundedCommunicationProfileVersion.workspace_id == workspace_id,
                BoundedCommunicationProfileVersion.canvas_id == canvas_id,
            )
        )
        if profile is None:
            raise AgentStudioNotFoundError()
        if source_invocation_id is not None:
            await self._owned_invocation(
                user_id,
                workspace_id,
                canvas_id,
                source_invocation_id,
            )
        original = _bounded_text(original_text, 40_000)
        revised = _bounded_text(revised_text, 40_000)
        protected = _protected_facts(original, citation_ids)
        missing = _missing_protected(protected, revised)
        status = "preserved" if not missing else "rejected"
        failure = None if not missing else "protected_fact_changed"
        original_digest = _text_digest(original)
        revised_digest = _text_digest(revised)
        facts_digest = _digest(protected)
        existing = await self.session.scalar(
            select(BoundedCommunicationRevision).where(
                BoundedCommunicationRevision.user_id == user_id,
                BoundedCommunicationRevision.workspace_id == workspace_id,
                BoundedCommunicationRevision.canvas_id == canvas_id,
                BoundedCommunicationRevision.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.original_digest != original_digest
                or existing.revised_digest != revised_digest
                or existing.profile_version_id != profile_version_id
            ):
                raise AgentStudioConflictError()
            return existing
        revision_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:communication-revision:{user_id}:{workspace_id}:{canvas_id}:{idempotency_key}",
        )
        trace_id = uuid.uuid5(revision_id, "trace")
        row = BoundedCommunicationRevision(
            revision_id=revision_id,
            profile_version_id=profile_version_id,
            source_invocation_id=source_invocation_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            original_text=original,
            revised_text=revised,
            original_digest=original_digest,
            revised_digest=revised_digest,
            protected_facts=protected,
            protected_facts_digest=facts_digest,
            preservation_status=status,
            safe_failure_code=failure,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            created_at=self.now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                await self.events.record(
                    CreateDomainEvent(
                        event_type="agent.communication.revision_proposed",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        canvas_id=canvas_id,
                        subject_id=revision_id,
                        actor_user_id=user_id,
                        source_identity=f"communication-revision:{revision_id}:proposed",
                        trace_id=trace_id,
                        payload={"preservationStatus": status},
                        origin_type="authenticated_user",
                        related_id=source_invocation_id,
                    )
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def decide_communication_revision(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        revision_id: uuid.UUID,
        decision: Literal["accepted", "rejected"],
    ) -> BoundedCommunicationRevisionDecision:
        await self._authorize_operation(
            "communication_revision.decide",
            user_id,
            workspace_id,
            canvas_id,
        )
        revision = await self.session.scalar(
            select(BoundedCommunicationRevision).where(
                BoundedCommunicationRevision.revision_id == revision_id,
                BoundedCommunicationRevision.user_id == user_id,
                BoundedCommunicationRevision.workspace_id == workspace_id,
                BoundedCommunicationRevision.canvas_id == canvas_id,
            )
        )
        if revision is None:
            raise AgentStudioNotFoundError()
        if decision == "accepted" and revision.preservation_status != "preserved":
            raise AgentStudioAuthorityError()
        existing = await self.session.scalar(
            select(BoundedCommunicationRevisionDecision).where(
                BoundedCommunicationRevisionDecision.revision_id == revision_id
            )
        )
        if existing is not None:
            if existing.decision != decision:
                raise AgentStudioConflictError()
            return existing
        row = BoundedCommunicationRevisionDecision(
            decision_id=uuid.uuid5(revision_id, decision),
            revision_id=revision_id,
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            decision=decision,
            decided_by_user_id=user_id,
            trace_id=revision.trace_id,
            decided_at=self.now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                await self.events.record(
                    CreateDomainEvent(
                        event_type=(
                            "agent.communication.revision_accepted"
                            if decision == "accepted"
                            else "agent.communication.revision_rejected"
                        ),
                        user_id=user_id,
                        workspace_id=workspace_id,
                        canvas_id=canvas_id,
                        subject_id=revision_id,
                        actor_user_id=user_id,
                        source_identity=f"communication-revision:{revision_id}:{decision}",
                        trace_id=revision.trace_id,
                        payload={
                            "preservationStatus": revision.preservation_status,
                            "decision": decision,
                        },
                        origin_type="authenticated_user",
                        related_id=revision.source_invocation_id,
                    )
                )
        except (IntegrityError, SQLAlchemyError) as exc:
            raise AgentStudioStorageError() from exc
        return row

    async def change_lifecycle(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        agent_id: uuid.UUID,
        operation: Literal["suspend", "restore", "retire"],
        reason_code: str,
    ) -> AgentRecord:
        await self._authorize_operation(
            f"agent.lifecycle.{operation}",
            user_id,
            workspace_id,
            canvas_id,
        )
        identity = await self._owned_agent(user_id, workspace_id, canvas_id, agent_id)
        current = await self._agent_lifecycle(agent_id)
        target: AgentLifecycle
        if operation == "suspend":
            if current is AgentLifecycle.SUSPENDED:
                return await self.get_agent(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    agent_id=agent_id,
                    duplicate=True,
                )
            if current is not AgentLifecycle.ACTIVE:
                raise AgentStudioConflictError()
            target = AgentLifecycle.SUSPENDED
        elif operation == "restore":
            if current is not AgentLifecycle.SUSPENDED:
                raise AgentStudioConflictError()
            if await self._active_version(agent_id) is None:
                raise AgentStudioAuthorityError()
            target = AgentLifecycle.ACTIVE
        else:
            if current is AgentLifecycle.RETIRED:
                return await self.get_agent(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    agent_id=agent_id,
                    duplicate=True,
                )
            target = AgentLifecycle.RETIRED
        trace_id = uuid.uuid5(
            identity.trace_id,
            f"lifecycle:{operation}:{await self._agent_state_count(agent_id)}",
        )
        await self._agent_state(
            identity,
            target,
            trace_id=trace_id,
            reason_code=_reason_code(reason_code),
        )
        if operation in {"suspend", "retire"}:
            await self._event(
                ("agent.suspended" if operation == "suspend" else "agent.retired"),
                agent_id,
                identity,
                trace_id,
                payload={
                    "agentId": str(agent_id),
                    "lifecycleState": target.value,
                    "reasonCode": _reason_code(reason_code),
                },
            )
        return await self.get_agent(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            agent_id=agent_id,
        )

    async def list_agents(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        lifecycle: AgentLifecycle | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentRecord]:
        await self._scope(user_id, workspace_id, canvas_id)
        if limit < 1 or limit > 100 or offset < 0 or offset > 10_000:
            raise AgentStudioValidationError()
        rows = list(
            (
                await self.session.scalars(
                    select(BoundedAgentIdentity)
                    .where(
                        BoundedAgentIdentity.user_id == user_id,
                        BoundedAgentIdentity.workspace_id == workspace_id,
                        BoundedAgentIdentity.canvas_id == canvas_id,
                    )
                    .order_by(
                        BoundedAgentIdentity.created_at.desc(),
                        BoundedAgentIdentity.agent_id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        records = [
            await self.get_agent(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                agent_id=row.agent_id,
            )
            for row in rows
        ]
        return (
            records
            if lifecycle is None
            else [item for item in records if item.identity_state == lifecycle.value]
        )

    async def get_agent(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        agent_id: uuid.UUID,
        duplicate: bool = False,
    ) -> AgentRecord:
        identity = await self._owned_agent(user_id, workspace_id, canvas_id, agent_id)
        versions = tuple(
            (
                await self.session.scalars(
                    select(BoundedAgentVersion)
                    .where(BoundedAgentVersion.agent_id == agent_id)
                    .order_by(BoundedAgentVersion.version_number)
                )
            ).all()
        )
        states: dict[uuid.UUID, str] = {}
        for version in versions:
            states[version.version_id] = (await self._version_lifecycle(version.version_id)).value
        version_ids = [item.version_id for item in versions]
        validations = (
            tuple(
                (
                    await self.session.scalars(
                        select(BoundedAgentValidationReport)
                        .where(BoundedAgentValidationReport.agent_version_id.in_(version_ids))
                        .order_by(BoundedAgentValidationReport.created_at)
                    )
                ).all()
            )
            if version_ids
            else ()
        )
        requests = (
            tuple(
                (
                    await self.session.scalars(
                        select(BoundedAgentActivationRequest)
                        .where(BoundedAgentActivationRequest.agent_version_id.in_(version_ids))
                        .order_by(BoundedAgentActivationRequest.created_at)
                    )
                ).all()
            )
            if version_ids
            else ()
        )
        request_ids = [item.activation_request_id for item in requests]
        decisions = (
            tuple(
                (
                    await self.session.scalars(
                        select(BoundedAgentActivationDecision)
                        .where(
                            BoundedAgentActivationDecision.activation_request_id.in_(request_ids)
                        )
                        .order_by(BoundedAgentActivationDecision.decided_at)
                    )
                ).all()
            )
            if request_ids
            else ()
        )
        invocations = tuple(
            (
                await self.session.scalars(
                    select(BoundedAgentInvocation)
                    .where(BoundedAgentInvocation.agent_id == agent_id)
                    .order_by(BoundedAgentInvocation.created_at.desc())
                )
            ).all()
        )
        invocation_ids = [item.invocation_id for item in invocations]
        evaluations = (
            tuple(
                (
                    await self.session.scalars(
                        select(BoundedAgentEvaluation)
                        .where(BoundedAgentEvaluation.invocation_id.in_(invocation_ids))
                        .order_by(BoundedAgentEvaluation.created_at.desc())
                    )
                ).all()
            )
            if invocation_ids
            else ()
        )
        proposals = tuple(
            (
                await self.session.scalars(
                    select(BoundedAgentProposal)
                    .where(BoundedAgentProposal.agent_id == agent_id)
                    .order_by(BoundedAgentProposal.created_at.desc())
                )
            ).all()
        )
        return AgentRecord(
            identity=identity,
            identity_state=(await self._agent_lifecycle(agent_id)).value,
            versions=versions,
            version_states=states,
            validations=validations,
            activation_requests=requests,
            activation_decisions=decisions,
            invocations=invocations,
            evaluations=evaluations,
            proposals=proposals,
            duplicate=duplicate,
        )

    async def _persist_version(
        self,
        identity: BoundedAgentIdentity,
        definition: AgentVersionInput,
        *,
        idempotency_key: str,
        initial_state: AgentVersionLifecycle,
    ) -> BoundedAgentVersion:
        normalized = self._normalize_version(definition)
        content_digest = _digest(normalized)
        previous = await self.session.scalar(
            select(BoundedAgentVersion)
            .where(BoundedAgentVersion.agent_id == identity.agent_id)
            .order_by(BoundedAgentVersion.version_number.desc())
            .limit(1)
        )
        version_number = (previous.version_number if previous else 0) + 1
        version_id = uuid.uuid5(identity.agent_id, f"version:{idempotency_key}")
        trace_id = uuid.uuid5(version_id, "trace")
        row = BoundedAgentVersion(
            version_id=version_id,
            agent_id=identity.agent_id,
            user_id=identity.user_id,
            workspace_id=identity.workspace_id,
            canvas_id=identity.canvas_id,
            version_number=version_number,
            schema_version=AGENT_DEFINITION_SCHEMA_VERSION,
            purpose=definition.purpose,
            system_instruction=definition.system_instruction,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            selected_context_policy=definition.selected_context_policy,
            provider=definition.provider,
            model=definition.model,
            limits=definition.limits.model_dump(mode="json"),
            communication_policy=definition.communication_policy.model_dump(mode="json"),
            evaluation_policy=definition.evaluation_policy,
            risk_class=definition.risk_class.value,
            normalized_definition=normalized,
            content_digest=content_digest,
            idempotency_key=idempotency_key,
            supersedes_version_id=previous.version_id if previous else None,
            created_by_user_id=identity.user_id,
            trace_id=trace_id,
            created_at=self.now,
        )
        self.session.add(row)
        await self.session.flush()
        for ordinal, workflow_version_id in enumerate(definition.workflow_version_ids):
            workflow = await self.session.scalar(
                select(ControlledWorkflowVersion).where(
                    ControlledWorkflowVersion.version_id == workflow_version_id,
                    ControlledWorkflowVersion.user_id == identity.user_id,
                    ControlledWorkflowVersion.workspace_id == identity.workspace_id,
                    ControlledWorkflowVersion.canvas_id == identity.canvas_id,
                )
            )
            if workflow is None:
                raise AgentStudioAuthorityError()
            self.session.add(
                BoundedAgentWorkflowBinding(
                    binding_id=uuid.uuid5(version_id, f"workflow:{workflow_version_id}"),
                    agent_version_id=version_id,
                    workflow_version_id=workflow_version_id,
                    user_id=identity.user_id,
                    workspace_id=identity.workspace_id,
                    canvas_id=identity.canvas_id,
                    ordinal=ordinal,
                    workflow_digest=workflow.content_digest,
                    created_at=self.now,
                )
            )
        for item in definition.capability_requirements:
            self.session.add(
                BoundedAgentCapabilityRequirement(
                    requirement_id=uuid.uuid5(
                        version_id,
                        f"capability:{item.capability.value}:{item.resource_kind.value}",
                    ),
                    agent_version_id=version_id,
                    user_id=identity.user_id,
                    workspace_id=identity.workspace_id,
                    canvas_id=identity.canvas_id,
                    capability=item.capability.value,
                    resource_kind=item.resource_kind.value,
                    created_at=self.now,
                )
            )
        await self.session.flush()
        await self._version_state(row, initial_state, trace_id=trace_id)
        await self._event(
            "agent.version.created",
            version_id,
            identity,
            trace_id,
            related_id=identity.agent_id,
            payload={
                "agentId": str(identity.agent_id),
                "agentVersionId": str(version_id),
                "versionNumber": version_number,
                "lifecycleState": initial_state.value,
            },
        )
        return row

    async def _assert_version_references(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        definition: AgentVersionInput,
        *,
        require_active: bool,
    ) -> None:
        rows = list(
            (
                await self.session.scalars(
                    select(ControlledWorkflowVersion).where(
                        ControlledWorkflowVersion.version_id.in_(definition.workflow_version_ids),
                        ControlledWorkflowVersion.user_id == user_id,
                        ControlledWorkflowVersion.workspace_id == workspace_id,
                        ControlledWorkflowVersion.canvas_id == canvas_id,
                    )
                )
            ).all()
        )
        if {item.version_id for item in rows} != set(definition.workflow_version_ids):
            raise AgentStudioAuthorityError()
        if require_active:
            for row in rows:
                state = await self.session.scalar(
                    select(ControlledWorkflowVersionState.state)
                    .where(ControlledWorkflowVersionState.version_id == row.version_id)
                    .order_by(ControlledWorkflowVersionState.sequence.desc())
                    .limit(1)
                )
                if state != "active":
                    raise AgentStudioNotFoundError()

    async def _assert_persisted_bindings(
        self,
        version: BoundedAgentVersion,
        *,
        require_active: bool,
    ) -> None:
        bindings = await self._bindings(version.version_id)
        if not bindings:
            raise AgentStudioAuthorityError()
        for binding in bindings:
            workflow = await self.session.scalar(
                select(ControlledWorkflowVersion).where(
                    ControlledWorkflowVersion.version_id == binding.workflow_version_id,
                    ControlledWorkflowVersion.user_id == version.user_id,
                    ControlledWorkflowVersion.workspace_id == version.workspace_id,
                    ControlledWorkflowVersion.canvas_id == version.canvas_id,
                )
            )
            if workflow is None or workflow.content_digest != binding.workflow_digest:
                raise AgentStudioAuthorityError()
            if require_active:
                state = await self.session.scalar(
                    select(ControlledWorkflowVersionState.state)
                    .where(ControlledWorkflowVersionState.version_id == workflow.version_id)
                    .order_by(ControlledWorkflowVersionState.sequence.desc())
                    .limit(1)
                )
                if state != "active":
                    raise AgentStudioAuthorityError()

    async def _agent_state(
        self,
        identity: BoundedAgentIdentity,
        state: AgentLifecycle,
        *,
        trace_id: uuid.UUID,
        reason_code: str | None = None,
    ) -> BoundedAgentLifecycleState:
        sequence = await self._agent_state_count(identity.agent_id)
        row = BoundedAgentLifecycleState(
            state_id=uuid.uuid5(identity.agent_id, f"state:{sequence}:{state.value}"),
            agent_id=identity.agent_id,
            user_id=identity.user_id,
            workspace_id=identity.workspace_id,
            canvas_id=identity.canvas_id,
            sequence=sequence,
            state=state.value,
            reason_code=reason_code,
            actor_user_id=identity.user_id,
            trace_id=trace_id,
            recorded_at=self.now,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _version_state(
        self,
        version: BoundedAgentVersion,
        state: AgentVersionLifecycle,
        *,
        trace_id: uuid.UUID,
        reason_code: str | None = None,
    ) -> BoundedAgentVersionState:
        sequence = (
            await self.session.scalar(
                select(func.count())
                .select_from(BoundedAgentVersionState)
                .where(BoundedAgentVersionState.version_id == version.version_id)
            )
            or 0
        )
        row = BoundedAgentVersionState(
            state_id=uuid.uuid5(version.version_id, f"state:{sequence}:{state.value}"),
            version_id=version.version_id,
            user_id=version.user_id,
            workspace_id=version.workspace_id,
            canvas_id=version.canvas_id,
            sequence=sequence,
            state=state.value,
            reason_code=reason_code,
            actor_user_id=version.user_id,
            trace_id=trace_id,
            recorded_at=self.now,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _event(
        self,
        event_type: str,
        subject_id: uuid.UUID,
        identity: BoundedAgentIdentity,
        trace_id: uuid.UUID,
        *,
        related_id: uuid.UUID | None = None,
        payload: dict[str, object],
    ) -> None:
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=identity.user_id,
                workspace_id=identity.workspace_id,
                canvas_id=identity.canvas_id,
                subject_id=subject_id,
                actor_user_id=identity.user_id,
                source_identity=f"{event_type}:{subject_id}:{related_id or 'none'}",
                trace_id=trace_id,
                payload=cast(dict[str, JsonValue], _json_object(payload)),
                origin_type="authenticated_user",
                related_id=related_id,
            )
        )

    async def _owned_agent(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> BoundedAgentIdentity:
        row = await self.session.scalar(
            select(BoundedAgentIdentity).where(
                BoundedAgentIdentity.agent_id == agent_id,
                BoundedAgentIdentity.user_id == user_id,
                BoundedAgentIdentity.workspace_id == workspace_id,
                BoundedAgentIdentity.canvas_id == canvas_id,
            )
        )
        if row is None:
            raise AgentStudioNotFoundError()
        return row

    async def _owned_version(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> BoundedAgentVersion:
        row = await self.session.scalar(
            select(BoundedAgentVersion).where(
                BoundedAgentVersion.version_id == version_id,
                BoundedAgentVersion.user_id == user_id,
                BoundedAgentVersion.workspace_id == workspace_id,
                BoundedAgentVersion.canvas_id == canvas_id,
            )
        )
        if row is None:
            raise AgentStudioNotFoundError()
        return row

    async def _owned_invocation(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        invocation_id: uuid.UUID,
    ) -> BoundedAgentInvocation:
        row = await self.session.scalar(
            select(BoundedAgentInvocation).where(
                BoundedAgentInvocation.invocation_id == invocation_id,
                BoundedAgentInvocation.user_id == user_id,
                BoundedAgentInvocation.workspace_id == workspace_id,
                BoundedAgentInvocation.canvas_id == canvas_id,
            )
        )
        if row is None:
            raise AgentStudioNotFoundError()
        return row

    async def _owned_proposal(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        proposal_id: uuid.UUID,
    ) -> BoundedAgentProposal:
        row = await self.session.scalar(
            select(BoundedAgentProposal).where(
                BoundedAgentProposal.proposal_id == proposal_id,
                BoundedAgentProposal.user_id == user_id,
                BoundedAgentProposal.workspace_id == workspace_id,
                BoundedAgentProposal.canvas_id == canvas_id,
            )
        )
        if row is None:
            raise AgentStudioNotFoundError()
        return row

    async def _scope(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
    ) -> Canvas:
        row = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.owner_id == user_id,
            )
        )
        if row is None:
            raise AgentStudioNotFoundError()
        return row

    async def _authorize_operation(
        self,
        operation: str,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
    ) -> Canvas:
        """Current owner-only seam for future membership, role, and action policy checks."""

        if not operation or len(operation) > 80:
            raise AgentStudioValidationError()
        return await self._scope(user_id, workspace_id, canvas_id)

    async def _workspace(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Workspace:
        row = await self.session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.owner_id == user_id,
            )
        )
        if row is None:
            raise AgentStudioNotFoundError()
        return row

    async def _agent_lifecycle(self, agent_id: uuid.UUID) -> AgentLifecycle:
        state = await self.session.scalar(
            select(BoundedAgentLifecycleState.state)
            .where(BoundedAgentLifecycleState.agent_id == agent_id)
            .order_by(BoundedAgentLifecycleState.sequence.desc())
            .limit(1)
        )
        if state is None:
            raise AgentStudioConflictError()
        return AgentLifecycle(state)

    async def _version_lifecycle(
        self,
        version_id: uuid.UUID,
    ) -> AgentVersionLifecycle:
        state = await self.session.scalar(
            select(BoundedAgentVersionState.state)
            .where(BoundedAgentVersionState.version_id == version_id)
            .order_by(BoundedAgentVersionState.sequence.desc())
            .limit(1)
        )
        if state is None:
            raise AgentStudioConflictError()
        return AgentVersionLifecycle(state)

    async def _active_version(self, agent_id: uuid.UUID) -> BoundedAgentVersion | None:
        versions = list(
            (
                await self.session.scalars(
                    select(BoundedAgentVersion)
                    .where(BoundedAgentVersion.agent_id == agent_id)
                    .order_by(BoundedAgentVersion.version_number.desc())
                )
            ).all()
        )
        for version in versions:
            if await self._version_lifecycle(version.version_id) is AgentVersionLifecycle.ACTIVE:
                return version
        return None

    async def _bindings(
        self,
        version_id: uuid.UUID,
    ) -> list[BoundedAgentWorkflowBinding]:
        return list(
            (
                await self.session.scalars(
                    select(BoundedAgentWorkflowBinding)
                    .where(BoundedAgentWorkflowBinding.agent_version_id == version_id)
                    .order_by(BoundedAgentWorkflowBinding.ordinal)
                )
            ).all()
        )

    async def _requirements(
        self,
        version_id: uuid.UUID,
    ) -> list[BoundedAgentCapabilityRequirement]:
        return list(
            (
                await self.session.scalars(
                    select(BoundedAgentCapabilityRequirement)
                    .where(BoundedAgentCapabilityRequirement.agent_version_id == version_id)
                    .order_by(
                        BoundedAgentCapabilityRequirement.capability,
                        BoundedAgentCapabilityRequirement.resource_kind,
                    )
                )
            ).all()
        )

    async def _agent_state_count(self, agent_id: uuid.UUID) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(BoundedAgentLifecycleState)
                .where(BoundedAgentLifecycleState.agent_id == agent_id)
            )
            or 0
        )

    @staticmethod
    def _normalize_version(definition: AgentVersionInput) -> dict[str, object]:
        value = definition.model_dump(mode="json")
        value["workflow_version_ids"] = sorted(value["workflow_version_ids"])
        value["capability_requirements"] = sorted(
            value["capability_requirements"],
            key=lambda item: (item["capability"], item["resource_kind"]),
        )
        return cast(dict[str, object], value)

    @staticmethod
    def _idempotency(value: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", value):
            raise AgentStudioValidationError()

    @staticmethod
    def _proposal_definition(
        payload: dict[str, object],
    ) -> tuple[AgentKind, str, str, AgentVersionInput]:
        try:
            kind = AgentKind(str(payload["agentKind"]))
            name = _bounded_text(str(payload["displayName"]), 160)
            description = _bounded_text(str(payload["description"]), 1_000)
            version = AgentVersionInput.model_validate(payload["version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentStudioValidationError() from exc
        return kind, name, description, version

    def _profile_version(
        self,
        identity: BoundedCommunicationProfile,
        profile: CommunicationProfileInput,
        *,
        version_number: int,
        idempotency_key: str,
    ) -> BoundedCommunicationProfileVersion:
        normalized = profile.model_dump(mode="json")
        return BoundedCommunicationProfileVersion(
            profile_version_id=uuid.uuid5(
                identity.profile_id,
                f"version:{idempotency_key}",
            ),
            profile_id=identity.profile_id,
            user_id=identity.user_id,
            workspace_id=identity.workspace_id,
            canvas_id=identity.canvas_id,
            version_number=version_number,
            audience=profile.audience.value,
            reading_level=profile.reading_level.value,
            formality=profile.formality.value,
            verbosity=profile.verbosity.value,
            technical_depth=profile.technical_depth.value,
            orwell_rules=profile.orwell_rules,
            content_digest=_digest(normalized),
            idempotency_key=idempotency_key,
            created_by_user_id=identity.user_id,
            trace_id=identity.trace_id,
            created_at=self.now,
        )


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json_object(value: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise AgentStudioValidationError()
    return cast(dict[str, object], decoded)


def _bounded_text(value: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise AgentStudioValidationError()
    return normalized


def _reason_code(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[a-z0-9_:-]{1,64}", normalized):
        raise AgentStudioValidationError()
    return normalized


def _safe_recommendations(
    values: list[dict[str, object]],
) -> list[dict[str, object]]:
    if len(values) > 20:
        raise AgentStudioValidationError()
    safe: list[dict[str, object]] = []
    for item in values:
        decoded = _json_object(item)
        if len(json.dumps(decoded, ensure_ascii=False)) > 2_000:
            raise AgentStudioValidationError()
        safe.append(decoded)
    return safe


def _protected_facts(
    text: str,
    citation_ids: tuple[str, ...],
) -> dict[str, object]:
    citations = tuple(dict.fromkeys(citation_ids))
    if len(citations) > 100 or any(
        not re.fullmatch(r"[A-Za-z0-9._:/-]{1,160}", item) for item in citations
    ):
        raise AgentStudioValidationError()
    facts = {
        "numbersDatesMeasurements": sorted(set(_NUMBER_OR_DATE.findall(text))),
        "urls": sorted(set(_URL.findall(text))),
        "hashes": sorted(set(_HASH.findall(text))),
        "lockedQuotations": sorted(set(_QUOTE.findall(text))),
        "names": sorted(set(_NAME.findall(text))),
        "citationIds": list(citations),
        "requiredWarnings": [item for item in _PROTECTED_WARNINGS if item in text.casefold()],
    }
    return cast(dict[str, object], facts)


def _missing_protected(
    protected: dict[str, object],
    revised: str,
) -> list[str]:
    missing: list[str] = []
    for key in (
        "numbersDatesMeasurements",
        "urls",
        "hashes",
        "lockedQuotations",
        "names",
        "citationIds",
    ):
        for value in cast(list[str], protected[key]):
            if value not in revised:
                missing.append(f"{key}:{value}")
    folded = revised.casefold()
    for value in cast(list[str], protected["requiredWarnings"]):
        if value not in folded:
            missing.append(f"requiredWarnings:{value}")
    return missing


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "AGENT_DEFINITION_SCHEMA_VERSION",
    "AGENT_REGISTRY_VERSION",
    "AGENT_STUDIO_SCHEMA_VERSION",
    "AgentKind",
    "AgentLifecycle",
    "AgentLimits",
    "AgentRecord",
    "AgentStudioAuthorityError",
    "AgentStudioConflictError",
    "AgentStudioError",
    "AgentStudioNotFoundError",
    "AgentStudioStorageError",
    "AgentStudioValidationError",
    "AgentVersionInput",
    "AgentVersionLifecycle",
    "Audience",
    "BoundedAgentStudioService",
    "CapabilityRequirementInput",
    "CommunicationPolicyInput",
    "CommunicationProfileInput",
    "EvaluationOutcome",
    "Formality",
    "ProposalKind",
    "ReadingLevel",
    "TechnicalDepth",
    "ValidationOutcome",
    "Verbosity",
]
