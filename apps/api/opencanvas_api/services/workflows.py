from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    CanonicalCanvasObjectBinding,
    CanonicalObject,
    Canvas,
    ControlledAgentApproval,
    ControlledAgentCapabilityGrant,
    ControlledAgentReversibleWriteProposal,
    ControlledWorkflowDefinition,
    ControlledWorkflowDependency,
    ControlledWorkflowEvidenceLink,
    ControlledWorkflowExecution,
    ControlledWorkflowExecutionTransition,
    ControlledWorkflowPlanSnapshot,
    ControlledWorkflowStep,
    ControlledWorkflowStepAttempt,
    ControlledWorkflowStepExecution,
    ControlledWorkflowStepTransition,
    ControlledWorkflowVersion,
    ControlledWorkflowVersionState,
    GraphRetrievalCitation,
    GraphRetrievalRun,
    Workspace,
    WorkspaceGraphState,
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
    PolicyOutcome,
    ResourceKind,
    ResourceScope,
    RiskClass,
    contract_digest,
)
from opencanvas_api.services.agents.persistence import (
    ApprovalConsumptionAttempt,
    ControlledAgentRepository,
)
from opencanvas_api.services.agents.policy import PolicyRequest, evaluate_policy
from opencanvas_api.services.agents.reversible_write_effects import (
    ReversibleWriteEffectService,
)
from opencanvas_api.services.agents.reversible_write_proposals import (
    ReversibleWriteProposalService,
)
from opencanvas_api.services.agents.reversible_write_rollback_approvals import (
    ReversibleWriteRollbackApprovalService,
)
from opencanvas_api.services.agents.reversible_write_rollback_review import (
    ReversibleWriteRollbackReviewService,
)
from opencanvas_api.services.agents.reversible_write_rollbacks import (
    ReversibleWriteRollbackService,
)
from opencanvas_api.services.agents.reversible_writes import ReversibleWriteAction
from opencanvas_api.services.ai import (
    GROUNDED_PROMPT_VERSION,
    AIProvider,
    AIProviderError,
    GroundedSource,
    model_configuration,
)
from opencanvas_api.services.context import ContextBundle
from opencanvas_api.services.documents.embeddings import EmbeddingProvider
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.graph_retrieval import (
    APA_RENDERER_VERSION,
    BUNDLE_SCHEMA_VERSION,
    GraphAwareRetrievalService,
    GraphRetrievalError,
    RetrievalRecord,
    StartGraphRetrieval,
    TraceEvidenceBundleService,
)
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    RecordTraceEventInput,
    StartTraceInput,
    TraceErrorInfo,
    TraceService,
)

WORKFLOW_SCHEMA_VERSION = "controlled-workflow-v1"
PLAN_SCHEMA_VERSION = "controlled-workflow-plan-v1"
OUTPUT_SCHEMA_VERSION: Literal["controlled-workflow-output-v1"] = "controlled-workflow-output-v1"
POLICY_VERSION = "controlled-workflow-policy-v1"
MAX_WORKFLOW_STEPS = 32
MAX_DEPENDENCIES_PER_STEP = 8
MAX_SELECTED_CONTEXT = 50
MAX_RETRIEVAL_STEPS = 4
MAX_MODEL_STEPS = 4
MAX_APPROVAL_STEPS = 8
MAX_EFFECT_STEPS = 8
MAX_RETRIES_PER_STEP = 3
MAX_TOTAL_ATTEMPTS = 64
MAX_DURATION_SECONDS = 900
MAX_STEP_INPUT_BYTES = 64_000
MAX_STEP_OUTPUT_BYTES = 64_000
MAX_TOTAL_OUTPUT_BYTES = 128_000
MAX_BUNDLE_STEPS = 4
MAX_DESCRIPTION_CHARACTERS = 1_000
MAX_NAME_CHARACTERS = 160
STEP_LEASE_SECONDS = 60
RETRY_BASE_SECONDS = 2
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class WorkflowKind(StrEnum):
    GROUNDED_ANSWER = "grounded_answer"
    EVIDENCE_PACKAGE = "evidence_package"
    APPROVED_REVERSIBLE_NOTE = "approved_reversible_note"


class WorkflowVersionLifecycle(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISABLED = "disabled"
    RETIRED = "retired"


class WorkflowStepType(StrEnum):
    VALIDATE_INPUT = "validate_input"
    CAPTURE_CONTEXT = "capture_context"
    GRAPH_RETRIEVAL = "graph_retrieval"
    EVALUATE_EVIDENCE = "evaluate_evidence"
    GROUNDED_MODEL = "grounded_model"
    RENDER_CITATIONS = "render_citations"
    EVIDENCE_BUNDLE = "evidence_bundle"
    HUMAN_APPROVAL = "human_approval"
    CONTROLLED_EFFECT = "controlled_effect"
    COMPENSATION = "compensation"
    RECORD_OUTPUT = "record_output"


class WorkflowExecutionStatus(StrEnum):
    REQUESTED = "requested"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELING = "canceling"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    COMPENSATED = "compensated"
    COMPENSATION_FAILED = "compensation_failed"


class WorkflowStepStatus(StrEnum):
    PENDING = "pending"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY_WAITING = "retry_waiting"
    FAILED = "failed"
    CANCELED = "canceled"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    COMPENSATION_FAILED = "compensation_failed"
    SKIPPED = "skipped"


class WorkflowOutcome(StrEnum):
    SUPPORTED = "supported"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BOUNDED_RESULT = "bounded_result"
    EFFECT_COMMITTED = "effect_committed"
    COMPENSATED = "compensated"
    CANCELED = "canceled"
    FAILED = "failed"


class WorkflowFailureClass(StrEnum):
    RETRYABLE_PROVIDER = "retryable_provider_failure"
    RETRYABLE_INTERNAL = "retryable_internal_transient_failure"
    VALIDATION = "validation_failure"
    AUTHORITY = "authority_failure"
    APPROVAL_DENIED = "approval_denial"
    EVIDENCE = "evidence_failure"
    POLICY = "policy_failure"
    BOUNDED_LIMIT = "bounded_limit_failure"
    CANCELED = "canceled"
    EXHAUSTED = "exhausted_retry"


class CompensationOutcome(StrEnum):
    NOT_REQUIRED = "not_required"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPENSATED = "compensated"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepTypeSpec:
    capability: Capability
    risk: RiskClass
    approval_required: bool
    allowed_config_keys: frozenset[str]


STEP_TYPE_REGISTRY = MappingProxyType(
    {
        WorkflowStepType.VALIDATE_INPUT: StepTypeSpec(
            Capability.WORKFLOW_STEP_EXECUTE,
            RiskClass.R0_OBSERVATION,
            False,
            frozenset(),
        ),
        WorkflowStepType.CAPTURE_CONTEXT: StepTypeSpec(
            Capability.CONTEXT_SELECTED_READ,
            RiskClass.R0_OBSERVATION,
            False,
            frozenset(),
        ),
        WorkflowStepType.GRAPH_RETRIEVAL: StepTypeSpec(
            Capability.RETRIEVAL_SELECTED_SEARCH,
            RiskClass.R1_DRAFT,
            False,
            frozenset({"maxDepth", "topK", "minRelevance"}),
        ),
        WorkflowStepType.EVALUATE_EVIDENCE: StepTypeSpec(
            Capability.WORKFLOW_STEP_EXECUTE,
            RiskClass.R0_OBSERVATION,
            False,
            frozenset(),
        ),
        WorkflowStepType.GROUNDED_MODEL: StepTypeSpec(
            Capability.DRAFT_ANSWER_CREATE,
            RiskClass.R1_DRAFT,
            False,
            frozenset({"instructionTemplate"}),
        ),
        WorkflowStepType.RENDER_CITATIONS: StepTypeSpec(
            Capability.TRACE_SCOPED_READ,
            RiskClass.R0_OBSERVATION,
            False,
            frozenset(),
        ),
        WorkflowStepType.EVIDENCE_BUNDLE: StepTypeSpec(
            Capability.EVIDENCE_BUNDLE_CREATE,
            RiskClass.R2_TRANSIENT_ACTION,
            False,
            frozenset(),
        ),
        WorkflowStepType.HUMAN_APPROVAL: StepTypeSpec(
            Capability.WORKFLOW_STEP_EXECUTE,
            RiskClass.R2_TRANSIENT_ACTION,
            True,
            frozenset({"reasonCode"}),
        ),
        WorkflowStepType.CONTROLLED_EFFECT: StepTypeSpec(
            Capability.CANVAS_NOTE_CREATE,
            RiskClass.R3_DURABLE_WRITE,
            True,
            frozenset({"action", "title", "text", "noteId", "expectedRevision"}),
        ),
        WorkflowStepType.COMPENSATION: StepTypeSpec(
            Capability.CANVAS_NOTE_CREATE_ROLLBACK,
            RiskClass.R3_DURABLE_WRITE,
            True,
            frozenset({"effectStepKey"}),
        ),
        WorkflowStepType.RECORD_OUTPUT: StepTypeSpec(
            Capability.WORKFLOW_STEP_EXECUTE,
            RiskClass.R0_OBSERVATION,
            False,
            frozenset(),
        ),
    }
)

VERSION_TRANSITIONS = {
    WorkflowVersionLifecycle.DRAFT: frozenset(
        {WorkflowVersionLifecycle.VALIDATED, WorkflowVersionLifecycle.RETIRED}
    ),
    WorkflowVersionLifecycle.VALIDATED: frozenset(
        {
            WorkflowVersionLifecycle.ACTIVE,
            WorkflowVersionLifecycle.DISABLED,
            WorkflowVersionLifecycle.RETIRED,
        }
    ),
    WorkflowVersionLifecycle.ACTIVE: frozenset(
        {
            WorkflowVersionLifecycle.SUPERSEDED,
            WorkflowVersionLifecycle.DISABLED,
            WorkflowVersionLifecycle.RETIRED,
        }
    ),
    WorkflowVersionLifecycle.DISABLED: frozenset(
        {WorkflowVersionLifecycle.ACTIVE, WorkflowVersionLifecycle.RETIRED}
    ),
}

TERMINAL_WORKFLOW_STATUSES = frozenset(
    {
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.COMPENSATED,
        WorkflowExecutionStatus.COMPENSATION_FAILED,
    }
)
TERMINAL_STEP_STATUSES = frozenset(
    {
        WorkflowStepStatus.SUCCEEDED,
        WorkflowStepStatus.FAILED,
        WorkflowStepStatus.CANCELED,
        WorkflowStepStatus.COMPENSATED,
        WorkflowStepStatus.COMPENSATION_FAILED,
        WorkflowStepStatus.SKIPPED,
    }
)
RETRYABLE_FAILURES = frozenset(
    {WorkflowFailureClass.RETRYABLE_PROVIDER, WorkflowFailureClass.RETRYABLE_INTERNAL}
)


class WorkflowContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class WorkflowStepInput(WorkflowContractModel):
    step_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    step_type: WorkflowStepType
    depends_on: tuple[str, ...] = Field(default=(), max_length=MAX_DEPENDENCIES_PER_STEP)
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
    def dependencies_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("step dependencies must be unique")
        return tuple(sorted(value))


class WorkflowVersionInput(WorkflowContractModel):
    steps: tuple[WorkflowStepInput, ...] = Field(min_length=1, max_length=MAX_WORKFLOW_STEPS)
    input_schema_version: Literal["workflow-input-v1"] = "workflow-input-v1"
    output_schema_version: Literal["controlled-workflow-output-v1"] = OUTPUT_SCHEMA_VERSION
    max_duration_seconds: int = Field(default=MAX_DURATION_SECONDS, ge=1, le=MAX_DURATION_SECONDS)
    max_retries_per_step: int = Field(default=MAX_RETRIES_PER_STEP, ge=0, le=MAX_RETRIES_PER_STEP)
    compensation_policy: Literal["none", "predefined_saga"] = "none"


@dataclass(frozen=True, slots=True)
class CreateWorkflowDraft:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    kind: WorkflowKind
    name: str
    description: str
    version: WorkflowVersionInput
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CreateWorkflowVersion:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    definition_id: uuid.UUID
    version: WorkflowVersionInput
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class StartWorkflow:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    version_id: uuid.UUID
    query: str
    selected_object_ids: tuple[uuid.UUID, ...]
    seed_object_ids: tuple[uuid.UUID, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class WorkflowDefinitionRecord:
    definition: ControlledWorkflowDefinition
    versions: tuple[ControlledWorkflowVersion, ...]
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class WorkflowExecutionRecord:
    execution: ControlledWorkflowExecution
    steps: tuple[ControlledWorkflowStepExecution, ...]
    duplicate: bool = False


class WorkflowError(RuntimeError):
    code = "workflow_failed"
    safe_message = "The controlled workflow could not be completed."


class WorkflowValidationError(WorkflowError):
    code = "workflow_invalid"
    safe_message = "The controlled workflow request is invalid."


class WorkflowNotFoundError(WorkflowError):
    code = "workflow_not_found"
    safe_message = "Controlled workflow not found."


class WorkflowConflictError(WorkflowError):
    code = "workflow_conflict"
    safe_message = "The controlled workflow conflicts with existing state."


class WorkflowAuthorityError(WorkflowError):
    code = "workflow_authority_denied"
    safe_message = "Controlled workflow authority is unavailable."


class WorkflowStorageError(WorkflowError):
    code = "workflow_storage_failed"
    safe_message = "Controlled workflow persistence is temporarily unavailable."


class _PauseForApproval(RuntimeError):
    pass


class _StepFailure(RuntimeError):
    def __init__(self, failure: WorkflowFailureClass, message: str) -> None:
        super().__init__(message)
        self.failure = failure


class ControlledWorkflowService:
    """Human-started bounded workflow coordinator over existing authority services."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        embedding_provider: EmbeddingProvider,
        ai_provider: AIProvider,
        now: datetime | None = None,
        after_version: Any | None = None,
        after_execution: Any | None = None,
        after_plan: Any | None = None,
        after_step_result: Any | None = None,
        after_event: Any | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.ai_provider = ai_provider
        self.now = _utc(now or datetime.now(UTC))
        self.trace = TraceService(session)
        self.events = DomainEventService(session, after_event=after_event)
        self.agent_repository = ControlledAgentRepository(session)
        self.after_version = after_version
        self.after_execution = after_execution
        self.after_plan = after_plan
        self.after_step_result = after_step_result

    async def create_draft(self, command: CreateWorkflowDraft) -> WorkflowDefinitionRecord:
        await self._scope(command.user_id, command.workspace_id, command.canvas_id)
        name = " ".join(command.name.split())
        description = " ".join(command.description.split())
        if not name or len(name) > MAX_NAME_CHARACTERS:
            raise WorkflowValidationError("Workflow name is invalid.")
        if len(description) > MAX_DESCRIPTION_CHARACTERS:
            raise WorkflowValidationError("Workflow description is too long.")
        self._validate_idempotency(command.idempotency_key)
        normalized, step_values = self._normalize_version(command.kind, command.version)
        content_digest = _digest(normalized)
        definition_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:workflow-definition:{command.user_id}:{command.workspace_id}:"
            f"{command.canvas_id}:{command.idempotency_key}",
        )
        version_id = uuid.uuid5(definition_id, command.idempotency_key)
        existing = await self.session.scalar(
            select(ControlledWorkflowDefinition).where(
                ControlledWorkflowDefinition.definition_id == definition_id,
                ControlledWorkflowDefinition.user_id == command.user_id,
                ControlledWorkflowDefinition.workspace_id == command.workspace_id,
                ControlledWorkflowDefinition.canvas_id == command.canvas_id,
            )
        )
        if existing is not None:
            version = await self.session.get(ControlledWorkflowVersion, version_id)
            if (
                version is None
                or version.content_digest != content_digest
                or existing.name != name
                or existing.description != description
                or existing.kind != command.kind.value
            ):
                raise WorkflowConflictError()
            return WorkflowDefinitionRecord(
                existing,
                tuple(await self._versions(existing.definition_id)),
                True,
            )

        trace_id = uuid.uuid5(version_id, "trace")
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="workflow.definition",
                actor_id=str(command.user_id),
                actor_type="user",
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                object_id=definition_id,
                object_type="workflow_definition",
                operation="workflow.definition.create",
                metadata={
                    "workflowKind": command.kind.value,
                    "contentDigest": content_digest,
                },
            )
        )
        try:
            async with self.session.begin_nested():
                definition = ControlledWorkflowDefinition(
                    definition_id=definition_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    canvas_id=command.canvas_id,
                    schema_version=WORKFLOW_SCHEMA_VERSION,
                    kind=command.kind.value,
                    name=name,
                    description=description,
                    created_by_user_id=command.user_id,
                    trace_id=trace_id,
                    created_at=self.now,
                )
                self.session.add(definition)
                await self.session.flush()
                version = await self._persist_version(
                    definition=definition,
                    version_id=version_id,
                    version_number=1,
                    idempotency_key=command.idempotency_key,
                    normalized=normalized,
                    step_values=step_values,
                    request=command.version,
                    supersedes_version_id=None,
                    trace_id=trace_id,
                )
                await _run_hook(self.after_version)
                await self._version_state(
                    version,
                    WorkflowVersionLifecycle.DRAFT,
                    actor_user_id=command.user_id,
                    trace_id=trace_id,
                )
                await self._event(
                    "workflow.definition.created",
                    definition.definition_id,
                    command.user_id,
                    command.workspace_id,
                    command.canvas_id,
                    trace_id,
                    source="created",
                    payload={
                        "workflowKind": command.kind.value,
                        "versionNumber": 1,
                        "lifecycleState": "draft",
                    },
                )
                await self._event(
                    "workflow.version.created",
                    version.version_id,
                    command.user_id,
                    command.workspace_id,
                    command.canvas_id,
                    trace_id,
                    source="created",
                    related_id=definition.definition_id,
                    payload={
                        "workflowKind": command.kind.value,
                        "versionNumber": 1,
                        "lifecycleState": "draft",
                    },
                )
                await self.trace.complete_trace(
                    CompleteTraceInput(
                        trace_id=trace_id,
                        event_type="workflow.definition",
                        actor_id=str(command.user_id),
                        actor_type="user",
                        user_id=command.user_id,
                        workspace_id=command.workspace_id,
                        object_id=definition_id,
                        object_type="workflow_definition",
                        operation="workflow.definition.create",
                        metadata={"versionId": str(version_id)},
                    )
                )
        except WorkflowError:
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            raise WorkflowStorageError() from exc
        return WorkflowDefinitionRecord(definition, (version,))

    async def create_version(self, command: CreateWorkflowVersion) -> WorkflowDefinitionRecord:
        definition = await self._owned_definition(
            command.user_id,
            command.workspace_id,
            command.canvas_id,
            command.definition_id,
        )
        self._validate_idempotency(command.idempotency_key)
        kind = WorkflowKind(definition.kind)
        normalized, step_values = self._normalize_version(kind, command.version)
        content_digest = _digest(normalized)
        existing = await self.session.scalar(
            select(ControlledWorkflowVersion).where(
                ControlledWorkflowVersion.definition_id == definition.definition_id,
                ControlledWorkflowVersion.idempotency_key == command.idempotency_key,
            )
        )
        if existing is not None:
            if existing.content_digest != content_digest:
                raise WorkflowConflictError()
            return WorkflowDefinitionRecord(
                definition,
                tuple(await self._versions(definition.definition_id)),
                True,
            )
        versions = await self._versions(definition.definition_id)
        previous = versions[-1] if versions else None
        version_number = (previous.version_number if previous is not None else 0) + 1
        version_id = uuid.uuid5(definition.definition_id, command.idempotency_key)
        trace_id = uuid.uuid5(version_id, "trace")
        async with self.session.begin_nested():
            version = await self._persist_version(
                definition=definition,
                version_id=version_id,
                version_number=version_number,
                idempotency_key=command.idempotency_key,
                normalized=normalized,
                step_values=step_values,
                request=command.version,
                supersedes_version_id=previous.version_id if previous else None,
                trace_id=trace_id,
            )
            await _run_hook(self.after_version)
            await self._version_state(
                version,
                WorkflowVersionLifecycle.DRAFT,
                actor_user_id=command.user_id,
                trace_id=trace_id,
            )
            await self._event(
                "workflow.version.created",
                version.version_id,
                command.user_id,
                command.workspace_id,
                command.canvas_id,
                trace_id,
                source="created",
                related_id=definition.definition_id,
                payload={
                    "workflowKind": definition.kind,
                    "versionNumber": version_number,
                    "lifecycleState": "draft",
                },
            )
        return WorkflowDefinitionRecord(
            definition,
            tuple(await self._versions(definition.definition_id)),
        )

    async def validate_version(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> ControlledWorkflowVersion:
        version = await self._owned_version(user_id, workspace_id, canvas_id, version_id)
        if (
            await self._latest_version_state(version.version_id)
            is not WorkflowVersionLifecycle.DRAFT
        ):
            raise WorkflowConflictError()
        await self._assert_persisted_plan(version)
        await self._version_state(
            version,
            WorkflowVersionLifecycle.VALIDATED,
            actor_user_id=user_id,
            trace_id=version.trace_id,
        )
        await self._event(
            "workflow.version.validated",
            version.version_id,
            user_id,
            workspace_id,
            canvas_id,
            version.trace_id,
            source="validated",
            related_id=version.definition_id,
            payload={
                "workflowKind": (
                    await self._owned_definition(
                        user_id, workspace_id, canvas_id, version.definition_id
                    )
                ).kind,
                "versionNumber": version.version_number,
                "lifecycleState": "validated",
            },
        )
        return version

    async def activate_version(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> ControlledWorkflowVersion:
        version = await self._owned_version(user_id, workspace_id, canvas_id, version_id)
        state = await self._latest_version_state(version.version_id)
        if state is WorkflowVersionLifecycle.ACTIVE:
            return version
        if state not in {WorkflowVersionLifecycle.VALIDATED, WorkflowVersionLifecycle.DISABLED}:
            raise WorkflowConflictError()
        active = await self._active_version(version.definition_id)
        if active is not None and active.version_id != version.version_id:
            await self._version_state(
                active,
                WorkflowVersionLifecycle.SUPERSEDED,
                actor_user_id=user_id,
                trace_id=active.trace_id,
                reason_code="new_version_activated",
            )
        await self._version_state(
            version,
            WorkflowVersionLifecycle.ACTIVE,
            actor_user_id=user_id,
            trace_id=version.trace_id,
        )
        definition = await self._owned_definition(
            user_id, workspace_id, canvas_id, version.definition_id
        )
        await self._event(
            "workflow.version.activated",
            version.version_id,
            user_id,
            workspace_id,
            canvas_id,
            version.trace_id,
            source="activated",
            related_id=version.definition_id,
            payload={
                "workflowKind": definition.kind,
                "versionNumber": version.version_number,
                "lifecycleState": "active",
            },
        )
        return version

    async def disable_version(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> ControlledWorkflowVersion:
        version = await self._owned_version(user_id, workspace_id, canvas_id, version_id)
        if (
            await self._latest_version_state(version.version_id)
            is not WorkflowVersionLifecycle.ACTIVE
        ):
            raise WorkflowConflictError()
        await self._version_state(
            version,
            WorkflowVersionLifecycle.DISABLED,
            actor_user_id=user_id,
            trace_id=version.trace_id,
        )
        definition = await self._owned_definition(
            user_id, workspace_id, canvas_id, version.definition_id
        )
        await self._event(
            "workflow.version.disabled",
            version.version_id,
            user_id,
            workspace_id,
            canvas_id,
            version.trace_id,
            source="disabled",
            related_id=version.definition_id,
            payload={
                "workflowKind": definition.kind,
                "versionNumber": version.version_number,
                "lifecycleState": "disabled",
            },
        )
        return version

    async def start(self, command: StartWorkflow) -> WorkflowExecutionRecord:
        self._validate_idempotency(command.idempotency_key)
        version = await self._owned_version(
            command.user_id,
            command.workspace_id,
            command.canvas_id,
            command.version_id,
        )
        if (
            await self._latest_version_state(version.version_id)
            is not WorkflowVersionLifecycle.ACTIVE
        ):
            raise WorkflowAuthorityError()
        query = " ".join(command.query.split())
        selected = tuple(dict.fromkeys(command.selected_object_ids))
        seeds = tuple(dict.fromkeys(command.seed_object_ids))
        if not query or len(query) > 4_000:
            raise WorkflowValidationError("Workflow query is invalid.")
        if not selected or len(selected) > MAX_SELECTED_CONTEXT:
            raise WorkflowValidationError("Selected workflow context is invalid.")
        if not seeds or not set(seeds).issubset(selected):
            raise WorkflowValidationError("Workflow seeds must be selected context.")
        await self._selected_context(
            command.user_id,
            command.workspace_id,
            command.canvas_id,
            selected,
        )
        graph_revision = (
            await self.session.scalar(
                select(WorkspaceGraphState.revision).where(
                    WorkspaceGraphState.workspace_id == command.workspace_id
                )
            )
            or 0
        )
        normalized_input: dict[str, object] = {
            "query": query,
            "selectedObjectIds": [str(value) for value in selected],
            "seedObjectIds": [str(value) for value in seeds],
        }
        input_digest = _digest(normalized_input)
        request_digest = _digest(
            {
                "schemaVersion": WORKFLOW_SCHEMA_VERSION,
                "userId": str(command.user_id),
                "workspaceId": str(command.workspace_id),
                "canvasId": str(command.canvas_id),
                "versionId": str(version.version_id),
                "versionDigest": version.content_digest,
                "graphRevision": graph_revision,
                "inputDigest": input_digest,
                "idempotencyKey": command.idempotency_key,
                "providerConfigurationVersion": getattr(
                    self.ai_provider,
                    "configuration_version",
                    "unspecified-provider-contract-v1",
                ),
            }
        )
        existing = await self.session.scalar(
            select(ControlledWorkflowExecution).where(
                ControlledWorkflowExecution.user_id == command.user_id,
                ControlledWorkflowExecution.workspace_id == command.workspace_id,
                ControlledWorkflowExecution.canvas_id == command.canvas_id,
                ControlledWorkflowExecution.idempotency_key == command.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise WorkflowConflictError()
            return await self.get_execution(
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                canvas_id=command.canvas_id,
                execution_id=existing.execution_id,
                duplicate=True,
            )

        definition = await self._owned_definition(
            command.user_id,
            command.workspace_id,
            command.canvas_id,
            version.definition_id,
        )
        steps = await self._steps(version.version_id)
        dependencies = await self._dependencies(version.version_id)
        plan_payload = self._compile_plan(version, steps, dependencies)
        plan_digest = _digest(plan_payload)
        execution_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:workflow-execution:{command.user_id}:{command.workspace_id}:"
            f"{command.canvas_id}:{command.idempotency_key}",
        )
        plan_id = uuid.uuid5(execution_id, PLAN_SCHEMA_VERSION)
        trace_id = uuid.uuid5(execution_id, "trace")
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                parent_trace_id=version.trace_id,
                event_type="workflow.execution",
                actor_id=str(command.user_id),
                actor_type="user",
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                object_id=execution_id,
                object_type="workflow_execution",
                operation="workflow.execution.start",
                metadata={
                    "workflowDefinitionId": str(definition.definition_id),
                    "workflowVersionId": str(version.version_id),
                    "planDigest": plan_digest,
                    "inputDigest": input_digest,
                    "graphRevision": graph_revision,
                },
            )
        )
        try:
            async with self.session.begin_nested():
                execution = ControlledWorkflowExecution(
                    execution_id=execution_id,
                    definition_id=definition.definition_id,
                    version_id=version.version_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    canvas_id=command.canvas_id,
                    idempotency_key=command.idempotency_key,
                    request_digest=request_digest,
                    plan_id=plan_id,
                    plan_digest=plan_digest,
                    input_digest=input_digest,
                    normalized_input=normalized_input,
                    selected_object_ids=[str(value) for value in selected],
                    graph_revision=graph_revision,
                    status=WorkflowExecutionStatus.PLANNED.value,
                    outcome=None,
                    output=None,
                    output_digest=None,
                    trace_id=trace_id,
                    created_at=self.now,
                    deadline_at=self.now + timedelta(seconds=version.max_duration_seconds),
                    cancel_requested_at=None,
                    completed_at=None,
                )
                self.session.add(execution)
                await self.session.flush()
                await _run_hook(self.after_execution)
                plan = ControlledWorkflowPlanSnapshot(
                    plan_id=plan_id,
                    execution_id=execution_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    schema_version=PLAN_SCHEMA_VERSION,
                    plan_digest=plan_digest,
                    payload=plan_payload,
                    created_at=self.now,
                )
                self.session.add(plan)
                await self.session.flush()
                await _run_hook(self.after_plan)
                await self._execution_transition(
                    execution,
                    WorkflowExecutionStatus.REQUESTED,
                    from_status=None,
                )
                await self._execution_transition(
                    execution,
                    WorkflowExecutionStatus.PLANNED,
                    from_status=WorkflowExecutionStatus.REQUESTED,
                )
                dependency_targets = {item.step_id for item in dependencies}
                for step in steps:
                    is_compensation = step.step_type == WorkflowStepType.COMPENSATION.value
                    initial = (
                        WorkflowStepStatus.BLOCKED
                        if step.step_id in dependency_targets or is_compensation
                        else WorkflowStepStatus.READY
                    )
                    row = ControlledWorkflowStepExecution(
                        step_execution_id=uuid.uuid5(execution_id, str(step.step_id)),
                        workflow_execution_id=execution_id,
                        step_definition_id=step.step_id,
                        user_id=command.user_id,
                        workspace_id=command.workspace_id,
                        controlled_execution_id=None,
                        status=initial.value,
                        attempt_count=0,
                        max_attempts=step.max_attempts,
                        next_retry_at=None,
                        lease_owner_id=None,
                        lease_generation=0,
                        lease_expires_at=None,
                        approval_id=None,
                        retrieval_id=None,
                        bundle_id=None,
                        effect_id=None,
                        rollback_result_id=None,
                        output=None,
                        output_digest=None,
                        safe_failure_class=None,
                        started_at=None,
                        completed_at=None,
                    )
                    self.session.add(row)
                    await self.session.flush()
                    await self._step_transition(row, initial, from_status=None)
                await self._event(
                    "workflow.execution.requested",
                    execution_id,
                    command.user_id,
                    command.workspace_id,
                    command.canvas_id,
                    trace_id,
                    source="requested",
                    related_id=version.version_id,
                    payload={
                        "workflowDefinitionId": str(definition.definition_id),
                        "workflowVersionId": str(version.version_id),
                        "status": "requested",
                    },
                )
                await self._event(
                    "workflow.execution.planned",
                    execution_id,
                    command.user_id,
                    command.workspace_id,
                    command.canvas_id,
                    trace_id,
                    source="planned",
                    related_id=version.version_id,
                    payload={
                        "workflowDefinitionId": str(definition.definition_id),
                        "workflowVersionId": str(version.version_id),
                        "status": "planned",
                    },
                )
                await self._execution_transition(
                    execution,
                    WorkflowExecutionStatus.READY,
                    from_status=WorkflowExecutionStatus.PLANNED,
                )
        except WorkflowError:
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            raise WorkflowStorageError() from exc
        return await self.run_until_pause(
            user_id=command.user_id,
            workspace_id=command.workspace_id,
            canvas_id=command.canvas_id,
            execution_id=execution_id,
        )

    async def get_definition(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        definition_id: uuid.UUID,
    ) -> WorkflowDefinitionRecord:
        definition = await self._owned_definition(user_id, workspace_id, canvas_id, definition_id)
        return WorkflowDefinitionRecord(
            definition,
            tuple(await self._versions(definition.definition_id)),
        )

    async def get_execution(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        execution_id: uuid.UUID,
        duplicate: bool = False,
    ) -> WorkflowExecutionRecord:
        execution = await self.session.scalar(
            select(ControlledWorkflowExecution).where(
                ControlledWorkflowExecution.execution_id == execution_id,
                ControlledWorkflowExecution.user_id == user_id,
                ControlledWorkflowExecution.workspace_id == workspace_id,
                ControlledWorkflowExecution.canvas_id == canvas_id,
            )
        )
        if execution is None:
            raise WorkflowNotFoundError()
        rows = tuple(
            (
                await self.session.scalars(
                    select(ControlledWorkflowStepExecution)
                    .join(
                        ControlledWorkflowStep,
                        ControlledWorkflowStep.step_id
                        == ControlledWorkflowStepExecution.step_definition_id,
                    )
                    .where(ControlledWorkflowStepExecution.workflow_execution_id == execution_id)
                    .order_by(
                        ControlledWorkflowStep.ordinal,
                        ControlledWorkflowStepExecution.step_execution_id,
                    )
                )
            ).all()
        )
        return WorkflowExecutionRecord(execution, rows, duplicate)

    async def run_until_pause(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        execution_id: uuid.UUID,
        now: datetime | None = None,
    ) -> WorkflowExecutionRecord:
        self.now = _utc(now or self.now)
        record = await self.get_execution(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )
        execution = record.execution
        if WorkflowExecutionStatus(execution.status) in TERMINAL_WORKFLOW_STATUSES:
            return record
        if self.now >= _utc(execution.deadline_at):
            await self._fail_execution(
                execution,
                WorkflowFailureClass.BOUNDED_LIMIT,
                "workflow_deadline_exceeded",
            )
            return await self.get_execution(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                execution_id=execution_id,
            )
        total_attempts = sum(item.attempt_count for item in record.steps)
        while total_attempts < MAX_TOTAL_ATTEMPTS:
            await self._unlock_ready(execution)
            step_execution = await self._next_ready(execution)
            if step_execution is None:
                await self._derive_execution_state(execution)
                break
            step = await self.session.get(ControlledWorkflowStep, step_execution.step_definition_id)
            if step is None:
                await self._fail_execution(
                    execution,
                    WorkflowFailureClass.VALIDATION,
                    "workflow_step_missing",
                )
                break
            try:
                await self._run_step(execution, step, step_execution)
            except _PauseForApproval:
                await self._execution_transition(
                    execution,
                    WorkflowExecutionStatus.AWAITING_APPROVAL,
                    from_status=WorkflowExecutionStatus(execution.status),
                )
                await self._event(
                    "workflow.execution.awaiting_approval",
                    execution.execution_id,
                    execution.user_id,
                    execution.workspace_id,
                    execution.canvas_id,
                    execution.trace_id,
                    source=f"approval:{step_execution.step_execution_id}",
                    related_id=execution.version_id,
                    payload={
                        "workflowDefinitionId": str(execution.definition_id),
                        "workflowVersionId": str(execution.version_id),
                        "status": "awaiting_approval",
                    },
                )
                break
            total_attempts += 1
            if WorkflowExecutionStatus(execution.status) in TERMINAL_WORKFLOW_STATUSES:
                break
        if total_attempts >= MAX_TOTAL_ATTEMPTS:
            await self._fail_execution(
                execution,
                WorkflowFailureClass.BOUNDED_LIMIT,
                "workflow_total_attempts_exceeded",
            )
        return await self.get_execution(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )

    async def decide_approval(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        execution_id: uuid.UUID,
        step_execution_id: uuid.UUID,
        decision: ApprovalDecision,
        session_id: uuid.UUID,
    ) -> WorkflowExecutionRecord:
        record = await self.get_execution(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )
        execution = record.execution
        if (
            WorkflowExecutionStatus(execution.status)
            is not WorkflowExecutionStatus.AWAITING_APPROVAL
        ):
            raise WorkflowConflictError()
        step_execution = next(
            (item for item in record.steps if item.step_execution_id == step_execution_id),
            None,
        )
        if step_execution is None or step_execution.status != WorkflowStepStatus.AWAITING_APPROVAL:
            raise WorkflowNotFoundError()
        step = await self.session.get(ControlledWorkflowStep, step_execution.step_definition_id)
        if step is None:
            raise WorkflowNotFoundError()
        step_type = WorkflowStepType(step.step_type)
        if step_type is WorkflowStepType.CONTROLLED_EFFECT:
            if step_execution.controlled_execution_id is None:
                raise WorkflowConflictError()
            proposal_row = await self.session.scalar(
                select(ControlledAgentReversibleWriteProposal).where(
                    ControlledAgentReversibleWriteProposal.execution_id
                    == step_execution.controlled_execution_id,
                    ControlledAgentReversibleWriteProposal.user_id == user_id,
                    ControlledAgentReversibleWriteProposal.workspace_id == workspace_id,
                    ControlledAgentReversibleWriteProposal.canvas_id == canvas_id,
                )
            )
            if proposal_row is None:
                raise WorkflowConflictError()
            if decision is ApprovalDecision.APPROVED:
                proposal = ReversibleWriteProposalService(self.session, now=self.now)
                contract = proposal._proposal_from_row(proposal_row)
                await proposal.approve(
                    authenticated_user_id=user_id,
                    workspace_id=workspace_id,
                    execution_id=step_execution.controlled_execution_id,
                    presented_plan_digest=contract_digest(contract),
                    session_id=session_id,
                )
            else:
                await self._deny_controlled_approval(
                    execution_id=step_execution.controlled_execution_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
        elif step_type is WorkflowStepType.COMPENSATION:
            effect = await self._effect_for_compensation(execution, step)
            if decision is ApprovalDecision.APPROVED:
                issued = await ReversibleWriteRollbackApprovalService(
                    self.session, now=self.now
                ).issue(
                    authenticated_user_id=user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    effect_id=effect.effect_id,
                    idempotency_key=f"wf-rb-{step_execution.step_execution_id}",
                )
                step_execution.approval_id = issued.approval.rollback_approval_id
            else:
                await self._step_failure_terminal(
                    execution,
                    step,
                    step_execution,
                    WorkflowFailureClass.APPROVAL_DENIED,
                    "compensation_approval_denied",
                    compensation=True,
                )
        else:
            if step_execution.controlled_execution_id is None:
                raise WorkflowConflictError()
            grant_row = await self.session.scalar(
                select(ControlledAgentCapabilityGrant).where(
                    ControlledAgentCapabilityGrant.execution_id
                    == step_execution.controlled_execution_id,
                    ControlledAgentCapabilityGrant.user_id == user_id,
                    ControlledAgentCapabilityGrant.workspace_id == workspace_id,
                )
            )
            if grant_row is None:
                raise WorkflowAuthorityError()
            grant = ControlledAgentRepository._load_contract(
                CapabilityGrant, grant_row.payload, grant_row.payload_digest
            )
            if grant.approval_id is None:
                raise WorkflowAuthorityError()
            existing = await self.session.get(ControlledAgentApproval, grant.approval_id)
            if existing is not None:
                raise WorkflowConflictError()
            approval = ApprovalRecord(
                approval_id=grant.approval_id,
                session_id=session_id,
                policy_version=grant.policy_version,
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=grant.execution_id,
                grant_id=grant.grant_id,
                decision=decision,
                capabilities=grant.capabilities,
                resources=grant.resources,
                context_digest=grant.context_digest,
                plan_digest=grant.plan_digest,
                decided_at=self.now,
                expires_at=grant.expires_at,
            )
            await self.agent_repository.append_approval(approval, grant)
            if decision is ApprovalDecision.APPROVED:
                await self.agent_repository.append_state(
                    ExecutionStateRecord(
                        state_id=uuid.uuid4(),
                        execution_id=grant.execution_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        status=ExecutionStatus.READY,
                        recorded_at=self.now,
                    )
                )
            else:
                await self.agent_repository.append_state(
                    ExecutionStateRecord(
                        state_id=uuid.uuid4(),
                        execution_id=grant.execution_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        status=ExecutionStatus.DENIED,
                        recorded_at=self.now,
                        safe_reason_code="approval_denied",
                    )
                )
        event_type = (
            "workflow.approval.accepted"
            if decision is ApprovalDecision.APPROVED
            else "workflow.approval.denied"
        )
        await self._event(
            event_type,
            step_execution.step_execution_id,
            user_id,
            workspace_id,
            canvas_id,
            execution.trace_id,
            source=decision.value,
            related_id=execution.execution_id,
            execution_id=step_execution.controlled_execution_id,
            payload={
                "workflowExecutionId": str(execution.execution_id),
                "stepType": step.step_type,
                "status": ("ready" if decision is ApprovalDecision.APPROVED else "failed"),
                "approvalStatus": decision.value,
            },
        )
        if decision is ApprovalDecision.DENIED:
            if step_type is not WorkflowStepType.COMPENSATION:
                await self._step_failure_terminal(
                    execution,
                    step,
                    step_execution,
                    WorkflowFailureClass.APPROVAL_DENIED,
                    "approval_denied",
                )
            return await self.get_execution(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                execution_id=execution_id,
            )
        await self._step_transition(
            step_execution,
            WorkflowStepStatus.READY,
            from_status=WorkflowStepStatus.AWAITING_APPROVAL,
            reason_code="approval_accepted",
        )
        next_execution_status = (
            WorkflowExecutionStatus.COMPENSATING
            if step_type is WorkflowStepType.COMPENSATION
            else WorkflowExecutionStatus.READY
        )
        await self._execution_transition(
            execution,
            next_execution_status,
            from_status=WorkflowExecutionStatus.AWAITING_APPROVAL,
        )
        return await self.run_until_pause(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )

    async def request_cancellation(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> WorkflowExecutionRecord:
        record = await self.get_execution(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )
        execution = record.execution
        status = WorkflowExecutionStatus(execution.status)
        if status in TERMINAL_WORKFLOW_STATUSES:
            return record
        if status not in {
            WorkflowExecutionStatus.CANCEL_REQUESTED,
            WorkflowExecutionStatus.CANCELING,
        }:
            execution.cancel_requested_at = self.now
            await self._execution_transition(
                execution,
                WorkflowExecutionStatus.CANCEL_REQUESTED,
                from_status=status,
            )
        await self._execution_transition(
            execution,
            WorkflowExecutionStatus.CANCELING,
            from_status=WorkflowExecutionStatus.CANCEL_REQUESTED,
        )
        steps = await self._steps(execution.version_id)
        by_id = {step.step_id: step for step in steps}
        rows = record.steps
        has_effect = any(row.effect_id is not None for row in rows)
        version = await self.session.get(ControlledWorkflowVersion, execution.version_id)
        if version is None:
            raise WorkflowNotFoundError()
        for row in rows:
            step = by_id[row.step_definition_id]
            if WorkflowStepType(step.step_type) is WorkflowStepType.COMPENSATION:
                continue
            current = WorkflowStepStatus(row.status)
            if current not in TERMINAL_STEP_STATUSES:
                row.lease_owner_id = None
                row.lease_expires_at = None
                row.lease_generation += 1
                await self._step_transition(
                    row,
                    WorkflowStepStatus.CANCELED,
                    from_status=current,
                    reason_code="workflow_canceled",
                )
        if version.compensation_policy == "predefined_saga" and has_effect:
            for row in rows:
                step = by_id[row.step_definition_id]
                if WorkflowStepType(step.step_type) is WorkflowStepType.COMPENSATION:
                    await self._step_transition(
                        row,
                        WorkflowStepStatus.READY,
                        from_status=WorkflowStepStatus(row.status),
                        reason_code="cancellation_compensation_required",
                    )
            await self._execution_transition(
                execution,
                WorkflowExecutionStatus.COMPENSATING,
                from_status=WorkflowExecutionStatus.CANCELING,
            )
            await self._event(
                "workflow.compensation.started",
                execution.execution_id,
                user_id,
                workspace_id,
                canvas_id,
                execution.trace_id,
                source="cancel",
                related_id=execution.version_id,
                payload={
                    "workflowDefinitionId": str(execution.definition_id),
                    "workflowVersionId": str(execution.version_id),
                    "status": "compensating",
                },
            )
            return await self.run_until_pause(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                execution_id=execution_id,
            )
        execution.outcome = WorkflowOutcome.CANCELED.value
        execution.completed_at = self.now
        await self._execution_transition(
            execution,
            WorkflowExecutionStatus.CANCELED,
            from_status=WorkflowExecutionStatus.CANCELING,
        )
        await self._event(
            "workflow.execution.canceled",
            execution.execution_id,
            user_id,
            workspace_id,
            canvas_id,
            execution.trace_id,
            source="canceled",
            related_id=execution.version_id,
            payload={
                "workflowDefinitionId": str(execution.definition_id),
                "workflowVersionId": str(execution.version_id),
                "status": "canceled",
                "outcome": "canceled",
            },
        )
        await self.trace.record_event(
            RecordTraceEventInput(
                trace_id=execution.trace_id,
                parent_trace_id=None,
                event_type="workflow.execution",
                actor_id=str(user_id),
                actor_type="user",
                user_id=user_id,
                workspace_id=workspace_id,
                object_id=execution.execution_id,
                object_type="workflow_execution",
                operation="workflow.execution.cancel",
                status="succeeded",
                metadata={"outcome": "canceled"},
            )
        )
        return await self.get_execution(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )

    async def _run_step(
        self,
        execution: ControlledWorkflowExecution,
        step: ControlledWorkflowStep,
        row: ControlledWorkflowStepExecution,
    ) -> None:
        owner = str(uuid.uuid4())
        generation = row.lease_generation + 1
        claimed = await self.session.scalar(
            update(ControlledWorkflowStepExecution)
            .where(
                ControlledWorkflowStepExecution.step_execution_id == row.step_execution_id,
                ControlledWorkflowStepExecution.status.in_(
                    [WorkflowStepStatus.READY.value, WorkflowStepStatus.RETRY_WAITING.value]
                ),
                ControlledWorkflowStepExecution.attempt_count
                < ControlledWorkflowStepExecution.max_attempts,
                (
                    ControlledWorkflowStepExecution.next_retry_at.is_(None)
                    | (ControlledWorkflowStepExecution.next_retry_at <= self.now)
                ),
            )
            .values(
                status=WorkflowStepStatus.CLAIMED.value,
                lease_owner_id=owner,
                lease_generation=generation,
                lease_expires_at=min(
                    self.now + timedelta(seconds=STEP_LEASE_SECONDS),
                    _utc(execution.deadline_at),
                ),
                attempt_count=ControlledWorkflowStepExecution.attempt_count + 1,
                started_at=func.coalesce(ControlledWorkflowStepExecution.started_at, self.now),
                next_retry_at=None,
            )
            .execution_options(synchronize_session=False)
            .returning(ControlledWorkflowStepExecution.step_execution_id)
        )
        if claimed is None:
            raise WorkflowConflictError()
        await self.session.refresh(row)
        await self._step_transition(
            row,
            WorkflowStepStatus.CLAIMED,
            from_status=WorkflowStepStatus.READY
            if row.attempt_count == 1
            else WorkflowStepStatus.RETRY_WAITING,
        )
        await self._step_transition(
            row,
            WorkflowStepStatus.RUNNING,
            from_status=WorkflowStepStatus.CLAIMED,
        )
        await self._execution_transition_if_needed(execution, WorkflowExecutionStatus.RUNNING)
        step_trace_id = uuid.uuid5(
            row.step_execution_id, f"attempt:{row.attempt_count}:generation:{generation}"
        )
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=step_trace_id,
                parent_trace_id=execution.trace_id,
                event_type="workflow.step",
                actor_id="controlled-workflow-service",
                actor_type="service",
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                object_id=row.step_execution_id,
                object_type="workflow_step",
                operation=f"workflow.step.{step.step_type}",
                metadata={
                    "workflowExecutionId": str(execution.execution_id),
                    "stepKey": step.step_key,
                    "stepType": step.step_type,
                    "attempt": row.attempt_count,
                    "stepDigest": step.step_digest,
                },
            )
        )
        await self._event(
            "workflow.step.started",
            row.step_execution_id,
            execution.user_id,
            execution.workspace_id,
            execution.canvas_id,
            step_trace_id,
            source=f"attempt:{row.attempt_count}:generation:{generation}:started",
            related_id=execution.execution_id,
            execution_id=row.controlled_execution_id,
            payload={
                "workflowExecutionId": str(execution.execution_id),
                "stepType": step.step_type,
                "status": "running",
                "attemptNumber": row.attempt_count,
            },
        )
        input_digest = _digest(
            {
                "workflowExecutionId": str(execution.execution_id),
                "requestDigest": execution.request_digest,
                "planDigest": execution.plan_digest,
                "stepDigest": step.step_digest,
                "attempt": row.attempt_count,
            }
        )
        try:
            output = await self._handler(execution, step, row, step_trace_id)
            if isinstance(output, _PauseForApproval):
                row.attempt_count = max(0, row.attempt_count - 1)
                row.lease_owner_id = None
                row.lease_expires_at = None
                await self._step_transition(
                    row,
                    WorkflowStepStatus.AWAITING_APPROVAL,
                    from_status=WorkflowStepStatus.RUNNING,
                    reason_code="human_approval_required",
                )
                await self._event(
                    "workflow.step.awaiting_approval",
                    row.step_execution_id,
                    execution.user_id,
                    execution.workspace_id,
                    execution.canvas_id,
                    step_trace_id,
                    source="awaiting-approval",
                    related_id=execution.execution_id,
                    execution_id=row.controlled_execution_id,
                    payload={
                        "workflowExecutionId": str(execution.execution_id),
                        "stepType": step.step_type,
                        "status": "awaiting_approval",
                        "approvalStatus": "requested",
                    },
                )
                await self._event(
                    "workflow.approval.requested",
                    row.step_execution_id,
                    execution.user_id,
                    execution.workspace_id,
                    execution.canvas_id,
                    step_trace_id,
                    source="requested",
                    related_id=execution.execution_id,
                    execution_id=row.controlled_execution_id,
                    payload={
                        "workflowExecutionId": str(execution.execution_id),
                        "stepType": step.step_type,
                        "status": "awaiting_approval",
                        "approvalStatus": "requested",
                    },
                )
                raise _PauseForApproval()
            output_digest = _digest(output)
            if len(_json(output)) > MAX_STEP_OUTPUT_BYTES:
                raise _StepFailure(
                    WorkflowFailureClass.BOUNDED_LIMIT,
                    "workflow_step_output_too_large",
                )
            completed = await self.session.scalar(
                update(ControlledWorkflowStepExecution)
                .where(
                    ControlledWorkflowStepExecution.step_execution_id == row.step_execution_id,
                    ControlledWorkflowStepExecution.status == WorkflowStepStatus.RUNNING.value,
                    ControlledWorkflowStepExecution.lease_owner_id == owner,
                    ControlledWorkflowStepExecution.lease_generation == generation,
                    ControlledWorkflowStepExecution.lease_expires_at > self.now,
                )
                .values(
                    status=(
                        WorkflowStepStatus.COMPENSATED.value
                        if step.step_type == WorkflowStepType.COMPENSATION.value
                        else WorkflowStepStatus.SUCCEEDED.value
                    ),
                    output=output,
                    output_digest=output_digest,
                    lease_owner_id=None,
                    lease_expires_at=None,
                    completed_at=self.now,
                    safe_failure_class=None,
                )
                .execution_options(synchronize_session=False)
                .returning(ControlledWorkflowStepExecution.step_execution_id)
            )
            if completed is None:
                raise WorkflowConflictError()
            await self.session.refresh(row)
            await _run_hook(self.after_step_result)
            target_status = (
                WorkflowStepStatus.COMPENSATED
                if step.step_type == WorkflowStepType.COMPENSATION.value
                else WorkflowStepStatus.SUCCEEDED
            )
            await self._step_transition(
                row,
                target_status,
                from_status=WorkflowStepStatus.RUNNING,
            )
            config = model_configuration(self.ai_provider, grounded=True)
            self.session.add(
                ControlledWorkflowStepAttempt(
                    attempt_id=uuid.uuid5(row.step_execution_id, f"attempt:{row.attempt_count}"),
                    step_execution_id=row.step_execution_id,
                    attempt_number=row.attempt_count,
                    lease_generation=generation,
                    input_digest=input_digest,
                    output_digest=output_digest,
                    outcome="succeeded",
                    failure_class=None,
                    provider_id=(
                        str(config["provider"])
                        if step.step_type == WorkflowStepType.GROUNDED_MODEL.value
                        else None
                    ),
                    model_id=(
                        str(config["model"])
                        if step.step_type == WorkflowStepType.GROUNDED_MODEL.value
                        else None
                    ),
                    provider_configuration_version=(
                        str(config["providerConfigurationVersion"])
                        if step.step_type == WorkflowStepType.GROUNDED_MODEL.value
                        else None
                    ),
                    prompt_version=(
                        GROUNDED_PROMPT_VERSION
                        if step.step_type == WorkflowStepType.GROUNDED_MODEL.value
                        else None
                    ),
                    trace_id=step_trace_id,
                    started_at=self.now,
                    completed_at=self.now,
                )
            )
            await self.trace.complete_trace(
                CompleteTraceInput(
                    trace_id=step_trace_id,
                    parent_trace_id=execution.trace_id,
                    event_type="workflow.step",
                    actor_id="controlled-workflow-service",
                    actor_type="service",
                    user_id=execution.user_id,
                    workspace_id=execution.workspace_id,
                    object_id=row.step_execution_id,
                    object_type="workflow_step",
                    operation=f"workflow.step.{step.step_type}",
                    metadata={"outputDigest": output_digest},
                )
            )
            await self._event(
                "workflow.step.completed",
                row.step_execution_id,
                execution.user_id,
                execution.workspace_id,
                execution.canvas_id,
                step_trace_id,
                source=f"attempt:{row.attempt_count}:completed",
                related_id=execution.execution_id,
                execution_id=row.controlled_execution_id,
                payload={
                    "workflowExecutionId": str(execution.execution_id),
                    "stepType": step.step_type,
                    "status": target_status.value,
                    "attemptNumber": row.attempt_count,
                },
            )
        except _PauseForApproval:
            if row.status == WorkflowStepStatus.RUNNING.value:
                row.attempt_count = max(0, row.attempt_count - 1)
                row.lease_owner_id = None
                row.lease_expires_at = None
                await self._step_transition(
                    row,
                    WorkflowStepStatus.AWAITING_APPROVAL,
                    from_status=WorkflowStepStatus.RUNNING,
                    reason_code="human_approval_required",
                )
                await self._event(
                    "workflow.step.awaiting_approval",
                    row.step_execution_id,
                    execution.user_id,
                    execution.workspace_id,
                    execution.canvas_id,
                    step_trace_id,
                    source="awaiting-approval",
                    related_id=execution.execution_id,
                    execution_id=row.controlled_execution_id,
                    payload={
                        "workflowExecutionId": str(execution.execution_id),
                        "stepType": step.step_type,
                        "status": "awaiting_approval",
                        "approvalStatus": "requested",
                    },
                )
                await self._event(
                    "workflow.approval.requested",
                    row.step_execution_id,
                    execution.user_id,
                    execution.workspace_id,
                    execution.canvas_id,
                    step_trace_id,
                    source="requested",
                    related_id=execution.execution_id,
                    execution_id=row.controlled_execution_id,
                    payload={
                        "workflowExecutionId": str(execution.execution_id),
                        "stepType": step.step_type,
                        "status": "awaiting_approval",
                        "approvalStatus": "requested",
                    },
                )
            raise
        except WorkflowConflictError:
            raise
        except Exception as exc:
            failure = self._classify_failure(exc)
            await self._handle_step_failure(
                execution,
                step,
                row,
                step_trace_id,
                input_digest,
                generation,
                failure,
            )

    async def _handler(
        self,
        execution: ControlledWorkflowExecution,
        step: ControlledWorkflowStep,
        row: ControlledWorkflowStepExecution,
        trace_id: uuid.UUID,
    ) -> dict[str, object] | _PauseForApproval:
        step_type = WorkflowStepType(step.step_type)
        if step_type not in {
            WorkflowStepType.CONTROLLED_EFFECT,
            WorkflowStepType.COMPENSATION,
        }:
            capability, resource = await self._ensure_controlled_execution(
                execution, step, row, trace_id
            )
            await self._authorize_step(execution, step, row, capability, resource, trace_id)

        if step_type is WorkflowStepType.VALIDATE_INPUT:
            encoded = _json(execution.normalized_input)
            if len(encoded) > MAX_STEP_INPUT_BYTES:
                raise _StepFailure(WorkflowFailureClass.BOUNDED_LIMIT, "workflow_input_too_large")
            return {
                "status": "valid",
                "inputDigest": execution.input_digest,
                "requestDigest": execution.request_digest,
            }
        if step_type is WorkflowStepType.CAPTURE_CONTEXT:
            objects = await self._selected_context(
                execution.user_id,
                execution.workspace_id,
                execution.canvas_id,
                tuple(uuid.UUID(value) for value in execution.selected_object_ids),
            )
            return {
                "graphRevision": execution.graph_revision,
                "resources": [
                    {
                        "canonicalObjectId": str(item.id),
                        "version": item.version,
                        "lifecycleState": item.lifecycle_state,
                    }
                    for item in objects
                ],
            }
        if step_type is WorkflowStepType.GRAPH_RETRIEVAL:
            values = execution.normalized_input
            selected = tuple(
                uuid.UUID(value) for value in cast(list[str], values["selectedObjectIds"])
            )
            seeds = tuple(uuid.UUID(value) for value in cast(list[str], values["seedObjectIds"]))
            config = step.config
            record = await GraphAwareRetrievalService(
                self.session,
                embedding_provider=self.embedding_provider,
            ).retrieve(
                StartGraphRetrieval(
                    user_id=execution.user_id,
                    workspace_id=execution.workspace_id,
                    canvas_id=execution.canvas_id,
                    query=cast(str, values["query"]),
                    selected_object_ids=selected,
                    seed_object_ids=seeds,
                    idempotency_key=f"wf-ret-{row.step_execution_id}",
                    max_depth=cast(int, config.get("maxDepth", 2)),
                    top_k=cast(int, config.get("topK", 8)),
                    min_relevance=cast(float, config.get("minRelevance", 0.15)),
                )
            )
            if record.run.graph_revision != execution.graph_revision:
                raise _StepFailure(
                    WorkflowFailureClass.EVIDENCE,
                    "workflow_graph_revision_changed",
                )
            row.retrieval_id = record.run.retrieval_id
            await self._evidence(
                execution,
                row,
                "retrieval",
                record.run.retrieval_id,
                _digest(
                    {
                        "retrievalId": str(record.run.retrieval_id),
                        "outcome": record.run.outcome,
                        "graphRevision": record.run.graph_revision,
                    }
                ),
                record.run.trace_id,
                None,
            )
            for citation in record.citations:
                await self._evidence(
                    execution,
                    row,
                    "citation",
                    citation.citation_id,
                    citation.excerpt_sha256,
                    citation.trace_id,
                    citation.audit_event_id,
                )
            return {
                "retrievalId": str(record.run.retrieval_id),
                "outcome": record.run.outcome,
                "bounded": record.run.bounded,
                "citationIds": [str(item.citation_id) for item in record.citations],
                "graphRevision": record.run.graph_revision,
            }
        if step_type is WorkflowStepType.EVALUATE_EVIDENCE:
            record = await self._latest_retrieval(execution)
            return {
                "retrievalId": str(record.run.retrieval_id),
                "outcome": record.run.outcome,
                "sufficient": record.run.outcome in {"supported", "conflicting_evidence"},
                "conflict": record.run.outcome == "conflicting_evidence",
                "bounded": record.run.outcome == "bounded_result",
                "citationIds": [str(item.citation_id) for item in record.citations],
            }
        if step_type is WorkflowStepType.GROUNDED_MODEL:
            retrieval = await self._latest_retrieval(execution)
            if retrieval.run.outcome == "insufficient_evidence":
                text = "The selected sources lack sufficient evidence to complete this workflow."
                output = {
                    "text": text,
                    "insufficientEvidence": True,
                    "citationIds": [],
                    "provider": None,
                    "model": None,
                    "providerConfigurationVersion": None,
                    "promptVersion": GROUNDED_PROMPT_VERSION,
                    "externalCall": False,
                }
            else:
                sources = [_grounded_source(item) for item in retrieval.citations]
                query = cast(str, execution.normalized_input["query"])
                instruction = cast(str, step.config.get("instructionTemplate", "{query}")).replace(
                    "{query}", query
                )
                result = await self.ai_provider.generate_grounded(
                    instruction,
                    ContextBundle(node_ids=[], snapshot=[], rendered=""),
                    sources,
                )
                validated_ids = {str(item.citation_id) for item in retrieval.citations}
                model_ids = {item.source_id for item in result.citations}
                if not model_ids.issubset(validated_ids):
                    raise _StepFailure(
                        WorkflowFailureClass.EVIDENCE,
                        "model_citation_not_authoritative",
                    )
                config = model_configuration(self.ai_provider, grounded=True)
                output = {
                    "text": result.text,
                    "insufficientEvidence": result.insufficient_evidence,
                    "citationIds": sorted(model_ids),
                    "provider": config["provider"],
                    "model": config["model"],
                    "providerConfigurationVersion": config["providerConfigurationVersion"],
                    "promptVersion": GROUNDED_PROMPT_VERSION,
                    "inputTokens": result.input_tokens,
                    "outputTokens": result.output_tokens,
                    "totalTokens": result.total_tokens,
                    "externalCall": not self.ai_provider.mock,
                }
            model_evidence_id = uuid.uuid5(row.step_execution_id, "model-output")
            await self._evidence(
                execution,
                row,
                "model_output",
                model_evidence_id,
                _digest(output),
                trace_id,
                await self._append_step_audit(
                    execution,
                    row,
                    trace_id,
                    "workflow.model.completed",
                    (
                        AuditAttribute(key="output_digest", value=_digest(output)),
                        AuditAttribute(
                            key="provider",
                            value=cast(str | None, output["provider"]),
                        ),
                        AuditAttribute(
                            key="prompt_version",
                            value=GROUNDED_PROMPT_VERSION,
                        ),
                    ),
                ),
            )
            return output
        if step_type is WorkflowStepType.RENDER_CITATIONS:
            retrieval = await self._latest_retrieval(execution)
            rendered = await GraphAwareRetrievalService(
                self.session,
                embedding_provider=self.embedding_provider,
            ).render_apa(retrieval, user_id=execution.user_id)
            return {
                "rendererVersion": APA_RENDERER_VERSION,
                "citations": [
                    {
                        "citationId": str(item.citation_id),
                        "inText": item.in_text,
                        "reference": item.reference,
                    }
                    for item in rendered
                ],
            }
        if step_type is WorkflowStepType.EVIDENCE_BUNDLE:
            retrieval = await self._latest_retrieval(execution)
            bundle = await TraceEvidenceBundleService(self.session).generate(
                retrieval,
                user_id=execution.user_id,
            )
            row.bundle_id = bundle.bundle_id
            await self._evidence(
                execution,
                row,
                "evidence_bundle",
                bundle.bundle_id,
                cast(str, bundle.artifact_sha256),
                bundle.trace_id,
                bundle.audit_event_id,
            )
            return {
                "bundleId": str(bundle.bundle_id),
                "schemaVersion": BUNDLE_SCHEMA_VERSION,
                "state": bundle.state,
                "artifactSha256": bundle.artifact_sha256,
                "byteSize": bundle.byte_size,
            }
        if step_type is WorkflowStepType.HUMAN_APPROVAL:
            if not await self._approval_available(row):
                return _PauseForApproval()
            return {
                "approvalId": str(row.approval_id),
                "decision": "approved",
            }
        if step_type is WorkflowStepType.CONTROLLED_EFFECT:
            if row.controlled_execution_id is None:
                action = ReversibleWriteAction(cast(str, step.config.get("action")))
                prepared = await ReversibleWriteProposalService(self.session, now=self.now).prepare(
                    authenticated_user_id=execution.user_id,
                    workspace_id=execution.workspace_id,
                    canvas_id=execution.canvas_id,
                    action=action,
                    title=cast(str, step.config.get("title", "")),
                    text=cast(str, step.config.get("text", "")),
                    note_id=(
                        uuid.UUID(cast(str, step.config["noteId"]))
                        if step.config.get("noteId")
                        else None
                    ),
                    expected_revision=(
                        cast(int, step.config["expectedRevision"])
                        if step.config.get("expectedRevision") is not None
                        else None
                    ),
                    idempotency_key=f"wf-effect-{row.step_execution_id}",
                    include_rollback_authority=step.compensation_step_key is not None,
                )
                row.controlled_execution_id = prepared.proposal.execution_id
                row.approval_id = prepared.approval_id
                return _PauseForApproval()
            approval = await self.session.scalar(
                select(ControlledAgentApproval).where(
                    ControlledAgentApproval.execution_id == row.controlled_execution_id,
                    ControlledAgentApproval.decision == ApprovalDecision.APPROVED.value,
                )
            )
            if approval is None:
                return _PauseForApproval()
            applied = await ReversibleWriteEffectService(self.session, now=self.now).apply(
                authenticated_user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                execution_id=row.controlled_execution_id,
                idempotency_key=f"wf-effect-{row.step_execution_id}",
            )
            row.effect_id = applied.effect.effect_id
            await self._evidence(
                execution,
                row,
                "controlled_effect",
                applied.effect.effect_id,
                applied.effect.after_digest,
                applied.effect.trace_id,
                None,
            )
            return {
                "effectId": str(applied.effect.effect_id),
                "action": applied.effect.action,
                "resourceId": str(applied.effect.resulting_resource_id),
                "resultingRevision": applied.effect.resulting_revision,
                "duplicate": applied.duplicate,
            }
        if step_type is WorkflowStepType.COMPENSATION:
            effect = await self._effect_for_compensation(execution, step)
            if row.approval_id is None:
                review = await ReversibleWriteRollbackReviewService(
                    self.session, now=self.now
                ).review(
                    authenticated_user_id=execution.user_id,
                    workspace_id=execution.workspace_id,
                    canvas_id=execution.canvas_id,
                    effect_id=effect.effect_id,
                )
                if not review.eligible:
                    raise _StepFailure(
                        WorkflowFailureClass.AUTHORITY,
                        review.denial_reason or "compensation_ineligible",
                    )
                row.controlled_execution_id = effect.execution_id
                return _PauseForApproval()
            rollback_applied = await ReversibleWriteRollbackService(
                self.session, now=self.now
            ).apply(
                authenticated_user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                canvas_id=execution.canvas_id,
                effect_id=effect.effect_id,
                rollback_approval_id=row.approval_id,
                idempotency_key=f"wf-rb-{row.step_execution_id}",
            )
            row.rollback_result_id = rollback_applied.result.rollback_result_id
            await self._evidence(
                execution,
                row,
                "controlled_rollback",
                rollback_applied.result.rollback_result_id,
                rollback_applied.result.post_rollback_target_digest,
                rollback_applied.result.trace_id,
                None,
            )
            return {
                "rollbackResultId": str(rollback_applied.result.rollback_result_id),
                "effectId": str(effect.effect_id),
                "duplicate": rollback_applied.duplicate,
                "outcome": "compensated",
            }
        if step_type is WorkflowStepType.RECORD_OUTPUT:
            output = await self._workflow_output(execution)
            if len(_json(output)) > MAX_TOTAL_OUTPUT_BYTES:
                raise _StepFailure(
                    WorkflowFailureClass.BOUNDED_LIMIT,
                    "workflow_output_too_large",
                )
            return output
        raise _StepFailure(WorkflowFailureClass.VALIDATION, "unregistered_step_handler")

    async def _ensure_controlled_execution(
        self,
        execution: ControlledWorkflowExecution,
        step: ControlledWorkflowStep,
        row: ControlledWorkflowStepExecution,
        trace_id: uuid.UUID,
    ) -> tuple[Capability, ResourceScope]:
        spec = STEP_TYPE_REGISTRY[WorkflowStepType(step.step_type)]
        capability = Capability(step.capability)
        if capability is not spec.capability:
            raise _StepFailure(WorkflowFailureClass.POLICY, "workflow_capability_tampered")
        canvas_scope = ResourceScope(
            kind=ResourceKind.CANVAS,
            resource_id=execution.canvas_id,
        )
        if row.controlled_execution_id is not None:
            return capability, canvas_scope
        controlled_execution_id = uuid.uuid5(row.step_execution_id, "controlled-execution")
        selected = await self._selected_context(
            execution.user_id,
            execution.workspace_id,
            execution.canvas_id,
            tuple(uuid.UUID(value) for value in execution.selected_object_ids),
        )
        context = ContextSnapshot(
            snapshot_id=uuid.uuid5(controlled_execution_id, "context"),
            user_id=execution.user_id,
            workspace_id=execution.workspace_id,
            execution_id=controlled_execution_id,
            captured_at=self.now,
            resources=tuple(
                ContextResource(
                    scope=ResourceScope(
                        kind=ResourceKind.CANONICAL_OBJECT,
                        resource_id=item.id,
                        version=item.version,
                    ),
                    content_digest=_digest(
                        {
                            "canonicalObjectId": str(item.id),
                            "version": item.version,
                            "objectType": item.object_type,
                            "lifecycleState": item.lifecycle_state,
                        }
                    ),
                )
                for item in selected
            ),
        )
        plan = PlanSnapshot(
            plan_id=uuid.uuid5(controlled_execution_id, "plan"),
            user_id=execution.user_id,
            workspace_id=execution.workspace_id,
            execution_id=controlled_execution_id,
            role=_role_for_step(WorkflowStepType(step.step_type)),
            created_at=self.now,
            actions=(
                PlanAction(
                    action_id=uuid.uuid5(controlled_execution_id, "action"),
                    ordinal=0,
                    capability=capability,
                    resource=canvas_scope,
                    risk_class=RiskClass(step.risk_class),
                    expected_result_digest=step.step_digest,
                ),
            ),
        )
        approval_id = (
            uuid.uuid5(controlled_execution_id, "approval") if step.approval_required else None
        )
        grant = CapabilityGrant(
            grant_id=uuid.uuid5(controlled_execution_id, "grant"),
            policy_version=POLICY_VERSION,
            issuing_service="controlled-workflow-service",
            user_id=execution.user_id,
            workspace_id=execution.workspace_id,
            execution_id=controlled_execution_id,
            role=plan.role,
            capabilities=(capability,),
            resources=(canvas_scope,),
            context_digest=contract_digest(context),
            plan_digest=contract_digest(plan),
            issued_at=self.now,
            expires_at=_utc(execution.deadline_at),
            approval_required=step.approval_required,
            approval_id=approval_id,
        )
        controlled = ExecutionRecord(
            execution_id=controlled_execution_id,
            user_id=execution.user_id,
            workspace_id=execution.workspace_id,
            role=plan.role,
            context_snapshot_id=context.snapshot_id,
            context_digest=contract_digest(context),
            plan_id=plan.plan_id,
            plan_digest=contract_digest(plan),
            grant_id=grant.grant_id,
            created_at=self.now,
        )
        await self.agent_repository.append_bundle(
            execution=controlled,
            context=context,
            plan=plan,
            grant=grant,
        )
        await self.agent_repository.append_state(
            ExecutionStateRecord(
                state_id=uuid.uuid4(),
                execution_id=controlled_execution_id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                status=ExecutionStatus.PROPOSED,
                recorded_at=self.now,
            )
        )
        await self.agent_repository.append_state(
            ExecutionStateRecord(
                state_id=uuid.uuid4(),
                execution_id=controlled_execution_id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                status=(
                    ExecutionStatus.AWAITING_APPROVAL
                    if step.approval_required
                    else ExecutionStatus.READY
                ),
                recorded_at=self.now,
            )
        )
        row.controlled_execution_id = controlled_execution_id
        row.approval_id = approval_id
        await self.agent_repository.append_audit_event(
            AuditEvent(
                event_id=uuid.uuid4(),
                trace_id=trace_id,
                execution_id=controlled_execution_id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                event_type="workflow.step.authority_prepared",
                recorded_at=self.now,
                attributes=(
                    AuditAttribute(key="workflow_execution_id", value=str(execution.execution_id)),
                    AuditAttribute(key="step_key", value=step.step_key),
                    AuditAttribute(key="capability", value=capability.value),
                    AuditAttribute(key="step_digest", value=step.step_digest),
                ),
            )
        )
        return capability, canvas_scope

    async def _authorize_step(
        self,
        execution: ControlledWorkflowExecution,
        step: ControlledWorkflowStep,
        row: ControlledWorkflowStepExecution,
        capability: Capability,
        resource: ResourceScope,
        trace_id: uuid.UUID,
    ) -> None:
        if row.controlled_execution_id is None:
            raise _StepFailure(WorkflowFailureClass.AUTHORITY, "controlled_execution_missing")
        inspection = await self.agent_repository.inspect_execution(
            user_id=execution.user_id,
            workspace_id=execution.workspace_id,
            execution_id=row.controlled_execution_id,
            limit=100,
            offset=0,
        )
        context_row = inspection.context
        plan_row = inspection.plan
        context = ControlledAgentRepository._load_contract(
            ContextSnapshot, context_row.payload, context_row.payload_digest
        )
        plan = ControlledAgentRepository._load_contract(
            PlanSnapshot, plan_row.payload, plan_row.payload_digest
        )
        grant_row = inspection.grants[-1] if inspection.grants else None
        if grant_row is None:
            raise _StepFailure(WorkflowFailureClass.AUTHORITY, "grant_missing")
        grant = ControlledAgentRepository._load_contract(
            CapabilityGrant, grant_row.payload, grant_row.payload_digest
        )
        if step.approval_required:
            if row.approval_id is None:
                raise _PauseForApproval()
            approval_row = await self.session.get(ControlledAgentApproval, row.approval_id)
            if approval_row is None:
                raise _PauseForApproval()
            decision = await self.agent_repository.consume_approval(
                ApprovalConsumptionAttempt(
                    consumption_id=uuid.uuid4(),
                    decision_id=uuid.uuid4(),
                    user_id=execution.user_id,
                    workspace_id=execution.workspace_id,
                    execution_id=row.controlled_execution_id,
                    approval_id=row.approval_id,
                    capability=capability,
                    resource=resource,
                    evaluated_at=self.now,
                )
            )
        else:
            revocations = tuple(
                ControlledAgentRepository._load_revocation(item.payload)
                for item in inspection.revocations
            )
            decision = evaluate_policy(
                PolicyRequest(
                    decision_id=uuid.uuid4(),
                    policy_version=grant.policy_version,
                    evaluated_at=self.now,
                    user_id=execution.user_id,
                    workspace_id=execution.workspace_id,
                    execution_id=row.controlled_execution_id,
                    capability=capability,
                    resource=resource,
                    context=context,
                    plan=plan,
                ),
                grant=grant,
                revocations=revocations,
            )
            await self.agent_repository.append_policy_decision(decision)
        if decision.outcome is not PolicyOutcome.ALLOW:
            raise _StepFailure(WorkflowFailureClass.AUTHORITY, decision.reason_code)
        await self._append_step_audit(
            execution,
            row,
            trace_id,
            "workflow.step.authorized",
            (
                AuditAttribute(key="step_key", value=step.step_key),
                AuditAttribute(key="capability", value=capability.value),
                AuditAttribute(key="policy_outcome", value=decision.outcome.value),
                AuditAttribute(key="policy_reason", value=decision.reason_code),
                AuditAttribute(key="request_digest", value=execution.request_digest),
                AuditAttribute(key="plan_digest", value=execution.plan_digest),
            ),
        )

    async def _handle_step_failure(
        self,
        execution: ControlledWorkflowExecution,
        step: ControlledWorkflowStep,
        row: ControlledWorkflowStepExecution,
        trace_id: uuid.UUID,
        input_digest: str,
        generation: int,
        failure: WorkflowFailureClass,
    ) -> None:
        retry = failure in RETRYABLE_FAILURES and row.attempt_count < row.max_attempts
        row.lease_owner_id = None
        row.lease_expires_at = None
        row.safe_failure_class = failure.value
        if retry:
            delay = min(RETRY_BASE_SECONDS * (2 ** (row.attempt_count - 1)), 30)
            next_retry = self.now + timedelta(seconds=delay)
            if next_retry >= _utc(execution.deadline_at):
                retry = False
            else:
                row.next_retry_at = next_retry
                await self._step_transition(
                    row,
                    WorkflowStepStatus.RETRY_WAITING,
                    from_status=WorkflowStepStatus.RUNNING,
                    reason_code=failure.value,
                )
                self.session.add(
                    ControlledWorkflowStepAttempt(
                        attempt_id=uuid.uuid5(
                            row.step_execution_id, f"attempt:{row.attempt_count}"
                        ),
                        step_execution_id=row.step_execution_id,
                        attempt_number=row.attempt_count,
                        lease_generation=generation,
                        input_digest=input_digest,
                        output_digest=None,
                        outcome="retry_scheduled",
                        failure_class=failure.value,
                        provider_id=None,
                        model_id=None,
                        provider_configuration_version=None,
                        prompt_version=None,
                        trace_id=trace_id,
                        started_at=self.now,
                        completed_at=self.now,
                    )
                )
                await self._event(
                    "workflow.step.retry_scheduled",
                    row.step_execution_id,
                    execution.user_id,
                    execution.workspace_id,
                    execution.canvas_id,
                    trace_id,
                    source=f"attempt:{row.attempt_count}:retry",
                    related_id=execution.execution_id,
                    execution_id=row.controlled_execution_id,
                    payload={
                        "workflowExecutionId": str(execution.execution_id),
                        "stepType": step.step_type,
                        "status": "retry_waiting",
                        "failureClass": failure.value,
                        "attemptNumber": row.attempt_count,
                        "retryAt": next_retry.isoformat(),
                    },
                )
        if not retry:
            terminal_failure = (
                WorkflowFailureClass.EXHAUSTED
                if failure in RETRYABLE_FAILURES and row.attempt_count >= row.max_attempts
                else failure
            )
            await self._step_failure_terminal(
                execution,
                step,
                row,
                terminal_failure,
                terminal_failure.value,
            )
            self.session.add(
                ControlledWorkflowStepAttempt(
                    attempt_id=uuid.uuid5(row.step_execution_id, f"attempt:{row.attempt_count}"),
                    step_execution_id=row.step_execution_id,
                    attempt_number=row.attempt_count,
                    lease_generation=generation,
                    input_digest=input_digest,
                    output_digest=None,
                    outcome="failed",
                    failure_class=terminal_failure.value,
                    provider_id=None,
                    model_id=None,
                    provider_configuration_version=None,
                    prompt_version=None,
                    trace_id=trace_id,
                    started_at=self.now,
                    completed_at=self.now,
                )
            )
        await self.trace.record_event(
            RecordTraceEventInput(
                trace_id=trace_id,
                parent_trace_id=execution.trace_id,
                event_type="workflow.step",
                actor_id="controlled-workflow-service",
                actor_type="service",
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                object_id=row.step_execution_id,
                object_type="workflow_step",
                operation=f"workflow.step.{step.step_type}",
                status="failed",
                metadata={"failureClass": failure.value, "retryScheduled": retry},
                error=TraceErrorInfo(
                    code=failure.value,
                    message="The workflow step did not complete.",
                ),
            )
        )

    async def _step_failure_terminal(
        self,
        execution: ControlledWorkflowExecution,
        step: ControlledWorkflowStep,
        row: ControlledWorkflowStepExecution,
        failure: WorkflowFailureClass,
        reason: str,
        *,
        compensation: bool = False,
    ) -> None:
        target = (
            WorkflowStepStatus.COMPENSATION_FAILED
            if compensation or step.step_type == WorkflowStepType.COMPENSATION.value
            else WorkflowStepStatus.FAILED
        )
        row.lease_owner_id = None
        row.lease_expires_at = None
        row.next_retry_at = None
        row.safe_failure_class = failure.value
        row.completed_at = self.now
        await self._step_transition(
            row,
            target,
            from_status=WorkflowStepStatus(row.status),
            reason_code=reason,
        )
        await self._event(
            "workflow.step.failed",
            row.step_execution_id,
            execution.user_id,
            execution.workspace_id,
            execution.canvas_id,
            execution.trace_id,
            source=f"failed:{row.attempt_count}:{failure.value}",
            related_id=execution.execution_id,
            execution_id=row.controlled_execution_id,
            payload={
                "workflowExecutionId": str(execution.execution_id),
                "stepType": step.step_type,
                "status": target.value,
                "failureClass": failure.value,
                "attemptNumber": row.attempt_count,
            },
        )
        if target is WorkflowStepStatus.COMPENSATION_FAILED:
            execution.outcome = WorkflowOutcome.FAILED.value
            execution.completed_at = self.now
            await self._execution_transition(
                execution,
                WorkflowExecutionStatus.COMPENSATION_FAILED,
                from_status=WorkflowExecutionStatus(execution.status),
                reason_code=reason,
            )
            await self._event(
                "workflow.compensation.failed",
                execution.execution_id,
                execution.user_id,
                execution.workspace_id,
                execution.canvas_id,
                execution.trace_id,
                source="failed",
                related_id=execution.version_id,
                payload={
                    "workflowDefinitionId": str(execution.definition_id),
                    "workflowVersionId": str(execution.version_id),
                    "status": "compensation_failed",
                    "outcome": "failed",
                    "reasonCode": reason,
                },
            )
        else:
            await self._fail_execution(execution, failure, reason)

    async def _fail_execution(
        self,
        execution: ControlledWorkflowExecution,
        failure: WorkflowFailureClass,
        reason: str,
    ) -> None:
        if WorkflowExecutionStatus(execution.status) in TERMINAL_WORKFLOW_STATUSES:
            return
        execution.outcome = WorkflowOutcome.FAILED.value
        execution.completed_at = self.now
        await self._execution_transition(
            execution,
            WorkflowExecutionStatus.FAILED,
            from_status=WorkflowExecutionStatus(execution.status),
            reason_code=reason,
        )
        await self._event(
            "workflow.execution.failed",
            execution.execution_id,
            execution.user_id,
            execution.workspace_id,
            execution.canvas_id,
            execution.trace_id,
            source=f"failed:{failure.value}",
            related_id=execution.version_id,
            payload={
                "workflowDefinitionId": str(execution.definition_id),
                "workflowVersionId": str(execution.version_id),
                "status": "failed",
                "outcome": "failed",
                "reasonCode": reason,
            },
        )

    async def _unlock_ready(self, execution: ControlledWorkflowExecution) -> None:
        rows = (
            await self.session.execute(
                select(ControlledWorkflowStepExecution, ControlledWorkflowStep)
                .join(
                    ControlledWorkflowStep,
                    ControlledWorkflowStep.step_id
                    == ControlledWorkflowStepExecution.step_definition_id,
                )
                .where(
                    ControlledWorkflowStepExecution.workflow_execution_id == execution.execution_id
                )
            )
        ).all()
        by_step = {step.step_id: row for row, step in rows}
        dependencies = await self._dependencies(execution.version_id)
        dependency_map: dict[uuid.UUID, set[uuid.UUID]] = {}
        for item in dependencies:
            dependency_map.setdefault(item.step_id, set()).add(item.depends_on_step_id)
        for row, step in rows:
            step_type = WorkflowStepType(step.step_type)
            if step_type is WorkflowStepType.COMPENSATION:
                continue
            if row.status == WorkflowStepStatus.RETRY_WAITING.value:
                if row.next_retry_at is not None and _utc(row.next_retry_at) <= self.now:
                    await self._step_transition(
                        row,
                        WorkflowStepStatus.READY,
                        from_status=WorkflowStepStatus.RETRY_WAITING,
                        reason_code="retry_eligible",
                    )
                continue
            if row.status != WorkflowStepStatus.BLOCKED.value:
                continue
            prerequisites = dependency_map.get(step.step_id, set())
            prerequisite_rows = [by_step[item] for item in prerequisites]
            if any(
                WorkflowStepStatus(item.status)
                in {
                    WorkflowStepStatus.FAILED,
                    WorkflowStepStatus.CANCELED,
                    WorkflowStepStatus.COMPENSATION_FAILED,
                }
                for item in prerequisite_rows
            ):
                await self._step_transition(
                    row,
                    WorkflowStepStatus.CANCELED,
                    from_status=WorkflowStepStatus.BLOCKED,
                    reason_code="required_dependency_failed",
                )
            elif prerequisite_rows and all(
                WorkflowStepStatus(item.status)
                in {
                    WorkflowStepStatus.SUCCEEDED,
                    WorkflowStepStatus.SKIPPED,
                    WorkflowStepStatus.COMPENSATED,
                }
                for item in prerequisite_rows
            ):
                await self._step_transition(
                    row,
                    WorkflowStepStatus.READY,
                    from_status=WorkflowStepStatus.BLOCKED,
                )

    async def _next_ready(
        self, execution: ControlledWorkflowExecution
    ) -> ControlledWorkflowStepExecution | None:
        return cast(
            ControlledWorkflowStepExecution | None,
            await self.session.scalar(
                select(ControlledWorkflowStepExecution)
                .join(
                    ControlledWorkflowStep,
                    ControlledWorkflowStep.step_id
                    == ControlledWorkflowStepExecution.step_definition_id,
                )
                .where(
                    ControlledWorkflowStepExecution.workflow_execution_id == execution.execution_id,
                    ControlledWorkflowStepExecution.status == WorkflowStepStatus.READY.value,
                )
                .order_by(
                    ControlledWorkflowStep.ordinal,
                    ControlledWorkflowStepExecution.step_execution_id,
                )
                .limit(1)
            ),
        )

    async def _derive_execution_state(self, execution: ControlledWorkflowExecution) -> None:
        record = await self.get_execution(
            user_id=execution.user_id,
            workspace_id=execution.workspace_id,
            canvas_id=execution.canvas_id,
            execution_id=execution.execution_id,
        )
        definitions = {item.step_id: item for item in await self._steps(execution.version_id)}
        compensation_required = execution.cancel_requested_at is not None and any(
            WorkflowStepType(definitions[row.step_definition_id].step_type)
            is WorkflowStepType.COMPENSATION
            and WorkflowStepStatus(row.status) is not WorkflowStepStatus.SKIPPED
            for row in record.steps
        )
        if not compensation_required:
            for row in record.steps:
                definition = definitions[row.step_definition_id]
                if (
                    WorkflowStepType(definition.step_type) is WorkflowStepType.COMPENSATION
                    and row.status == WorkflowStepStatus.BLOCKED.value
                ):
                    await self._step_transition(
                        row,
                        WorkflowStepStatus.SKIPPED,
                        from_status=WorkflowStepStatus.BLOCKED,
                        reason_code="compensation_not_required",
                    )
        statuses = {WorkflowStepStatus(item.status) for item in record.steps}
        if WorkflowStepStatus.AWAITING_APPROVAL in statuses:
            await self._execution_transition_if_needed(
                execution, WorkflowExecutionStatus.AWAITING_APPROVAL
            )
            return
        if WorkflowStepStatus.RETRY_WAITING in statuses:
            await self._execution_transition_if_needed(execution, WorkflowExecutionStatus.READY)
            return
        if any(
            status
            in {
                WorkflowStepStatus.PENDING,
                WorkflowStepStatus.BLOCKED,
                WorkflowStepStatus.READY,
                WorkflowStepStatus.CLAIMED,
                WorkflowStepStatus.RUNNING,
            }
            for status in statuses
        ):
            return
        if any(
            status in {WorkflowStepStatus.FAILED, WorkflowStepStatus.COMPENSATION_FAILED}
            for status in statuses
        ):
            await self._fail_execution(
                execution,
                WorkflowFailureClass.VALIDATION,
                "required_step_failed",
            )
            return
        if compensation_required:
            execution.outcome = WorkflowOutcome.COMPENSATED.value
            execution.completed_at = self.now
            await self._execution_transition(
                execution,
                WorkflowExecutionStatus.COMPENSATED,
                from_status=WorkflowExecutionStatus(execution.status),
            )
            await self._event(
                "workflow.compensation.completed",
                execution.execution_id,
                execution.user_id,
                execution.workspace_id,
                execution.canvas_id,
                execution.trace_id,
                source="completed",
                related_id=execution.version_id,
                payload={
                    "workflowDefinitionId": str(execution.definition_id),
                    "workflowVersionId": str(execution.version_id),
                    "status": "compensated",
                    "outcome": "compensated",
                },
            )
            return
        output = await self._workflow_output(execution)
        outcome = WorkflowOutcome(cast(str, output["outcome"]))
        execution.output = output
        execution.output_digest = _digest(output)
        execution.outcome = outcome.value
        execution.completed_at = self.now
        await self._execution_transition(
            execution,
            WorkflowExecutionStatus.COMPLETED,
            from_status=WorkflowExecutionStatus(execution.status),
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=execution.trace_id,
                event_type="workflow.execution",
                actor_id="controlled-workflow-service",
                actor_type="service",
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                object_id=execution.execution_id,
                object_type="workflow_execution",
                operation="workflow.execution.complete",
                metadata={
                    "outcome": outcome.value,
                    "outputDigest": execution.output_digest,
                },
            )
        )
        await self._event(
            "workflow.execution.completed",
            execution.execution_id,
            execution.user_id,
            execution.workspace_id,
            execution.canvas_id,
            execution.trace_id,
            source="completed",
            related_id=execution.version_id,
            payload={
                "workflowDefinitionId": str(execution.definition_id),
                "workflowVersionId": str(execution.version_id),
                "status": "completed",
                "outcome": outcome.value,
            },
        )

    def _normalize_version(
        self,
        kind: WorkflowKind,
        request: WorkflowVersionInput,
    ) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
        if len(request.steps) > MAX_WORKFLOW_STEPS:
            raise WorkflowValidationError("Workflow step limit exceeded.")
        keys = [item.step_key for item in request.steps]
        if len(keys) != len(set(keys)):
            raise WorkflowValidationError("Workflow step keys must be unique.")
        key_set = set(keys)
        step_types = [item.step_type for item in request.steps]
        counts = {
            "retrieval": step_types.count(WorkflowStepType.GRAPH_RETRIEVAL),
            "model": step_types.count(WorkflowStepType.GROUNDED_MODEL),
            "approval": sum(
                item.step_type
                in {
                    WorkflowStepType.HUMAN_APPROVAL,
                    WorkflowStepType.CONTROLLED_EFFECT,
                    WorkflowStepType.COMPENSATION,
                }
                for item in request.steps
            ),
            "effect": step_types.count(WorkflowStepType.CONTROLLED_EFFECT),
            "bundle": step_types.count(WorkflowStepType.EVIDENCE_BUNDLE),
        }
        if (
            counts["retrieval"] > MAX_RETRIEVAL_STEPS
            or counts["model"] > MAX_MODEL_STEPS
            or counts["approval"] > MAX_APPROVAL_STEPS
            or counts["effect"] > MAX_EFFECT_STEPS
            or counts["bundle"] > MAX_BUNDLE_STEPS
        ):
            raise WorkflowValidationError("Workflow operation limit exceeded.")
        if WorkflowStepType.RECORD_OUTPUT not in step_types:
            raise WorkflowValidationError("Workflow requires one bounded output step.")
        if step_types.count(WorkflowStepType.RECORD_OUTPUT) != 1:
            raise WorkflowValidationError("Workflow must have exactly one output step.")
        if kind in {WorkflowKind.GROUNDED_ANSWER, WorkflowKind.EVIDENCE_PACKAGE} and (
            WorkflowStepType.GRAPH_RETRIEVAL not in step_types
            or WorkflowStepType.EVALUATE_EVIDENCE not in step_types
        ):
            raise WorkflowValidationError("Grounded workflows require retrieval evaluation.")
        if kind is WorkflowKind.APPROVED_REVERSIBLE_NOTE and (
            WorkflowStepType.CONTROLLED_EFFECT not in step_types
        ):
            raise WorkflowValidationError("Reversible-note workflows require an effect step.")
        if request.compensation_policy == "predefined_saga":
            if (
                WorkflowStepType.CONTROLLED_EFFECT not in step_types
                or WorkflowStepType.COMPENSATION not in step_types
            ):
                raise WorkflowValidationError(
                    "Saga compensation requires effect and compensation steps."
                )
        elif WorkflowStepType.COMPENSATION in step_types:
            raise WorkflowValidationError("Compensation steps require the predefined saga policy.")
        normalized_steps: list[dict[str, object]] = []
        dependency_map: dict[str, tuple[str, ...]] = {}
        for ordinal, item in enumerate(request.steps):
            spec = STEP_TYPE_REGISTRY.get(item.step_type)
            if spec is None:
                raise WorkflowValidationError("Unknown workflow step type.")
            unknown_config = set(item.config) - spec.allowed_config_keys
            if unknown_config:
                raise WorkflowValidationError("Workflow step configuration is not allowed.")
            if item.step_key in item.depends_on:
                raise WorkflowValidationError("Workflow step cannot depend on itself.")
            if not set(item.depends_on).issubset(key_set):
                raise WorkflowValidationError("Workflow step dependency is missing.")
            if item.max_attempts > request.max_retries_per_step + 1:
                raise WorkflowValidationError("Workflow retry bound is inconsistent.")
            config = self._validate_step_config(item)
            capability = spec.capability
            if item.step_type is WorkflowStepType.CONTROLLED_EFFECT:
                capability = (
                    Capability.CANVAS_NOTE_UPDATE
                    if config.get("action") == ReversibleWriteAction.NOTE_UPDATE.value
                    else Capability.CANVAS_NOTE_CREATE
                )
            normalized = {
                "stepKey": item.step_key,
                "ordinal": ordinal,
                "stepType": item.step_type.value,
                "dependsOn": list(item.depends_on),
                "capability": capability.value,
                "riskClass": spec.risk.value,
                "approvalRequired": spec.approval_required,
                "maxAttempts": item.max_attempts,
                "config": config,
                "compensationStepKey": item.compensation_step_key,
            }
            normalized["stepDigest"] = _digest(normalized)
            normalized_steps.append(normalized)
            dependency_map[item.step_key] = item.depends_on
        self._validate_dag(dependency_map)
        compensation_keys = {
            item.step_key
            for item in request.steps
            if item.step_type is WorkflowStepType.COMPENSATION
        }
        for item in request.steps:
            if (
                item.compensation_step_key is not None
                and item.compensation_step_key not in compensation_keys
            ):
                raise WorkflowValidationError("Compensation reference is invalid.")
        normalized_definition: dict[str, object] = {
            "schemaVersion": WORKFLOW_SCHEMA_VERSION,
            "kind": kind.value,
            "inputSchemaVersion": request.input_schema_version,
            "outputSchemaVersion": request.output_schema_version,
            "steps": normalized_steps,
            "limits": {
                "maxSteps": len(normalized_steps),
                "maxDurationSeconds": request.max_duration_seconds,
                "maxRetriesPerStep": request.max_retries_per_step,
                "maxSelectedContext": MAX_SELECTED_CONTEXT,
                "maxTotalAttempts": MAX_TOTAL_ATTEMPTS,
                "maxStepInputBytes": MAX_STEP_INPUT_BYTES,
                "maxStepOutputBytes": MAX_STEP_OUTPUT_BYTES,
                "maxTotalOutputBytes": MAX_TOTAL_OUTPUT_BYTES,
            },
            "compensationPolicy": request.compensation_policy,
        }
        return normalized_definition, tuple(normalized_steps)

    def _validate_step_config(self, item: WorkflowStepInput) -> dict[str, object]:
        config = cast(dict[str, object], json.loads(_json(item.config)))
        if item.step_type is WorkflowStepType.GRAPH_RETRIEVAL:
            depth = cast(int, config.get("maxDepth", 2))
            top_k = cast(int, config.get("topK", 8))
            relevance = cast(float, config.get("minRelevance", 0.15))
            if not 1 <= depth <= 3 or not 1 <= top_k <= 50 or not 0 <= relevance <= 1:
                raise WorkflowValidationError("Retrieval bounds are invalid.")
            config = {"maxDepth": depth, "topK": top_k, "minRelevance": relevance}
        elif item.step_type is WorkflowStepType.GROUNDED_MODEL:
            template = str(config.get("instructionTemplate", "{query}")).strip()
            if len(template) > 8_000 or template not in {"{query}", "Answer: {query}"}:
                raise WorkflowValidationError("Prompt template is not registered.")
            config = {"instructionTemplate": template}
        elif item.step_type is WorkflowStepType.CONTROLLED_EFFECT:
            try:
                action = ReversibleWriteAction(cast(str, config.get("action")))
            except ValueError as exc:
                raise WorkflowValidationError("Controlled effect action is invalid.") from exc
            title = str(config.get("title", "")).strip()
            text = str(config.get("text", ""))
            if not title or len(title) > 300 or len(text) > 50_000:
                raise WorkflowValidationError("Controlled effect content is invalid.")
            note_id = config.get("noteId")
            expected_revision = config.get("expectedRevision")
            if action is ReversibleWriteAction.NOTE_CREATE:
                if note_id is not None or expected_revision is not None:
                    raise WorkflowValidationError("Create effect cannot bind an existing note.")
            else:
                try:
                    uuid.UUID(cast(str, note_id))
                except (ValueError, TypeError) as exc:
                    raise WorkflowValidationError("Update effect note is invalid.") from exc
                if not isinstance(expected_revision, int) or expected_revision < 0:
                    raise WorkflowValidationError("Update revision is invalid.")
            config = {
                "action": action.value,
                "title": title,
                "text": text,
                "noteId": note_id,
                "expectedRevision": expected_revision,
            }
        elif item.step_type is WorkflowStepType.COMPENSATION:
            key = str(config.get("effectStepKey", "")).strip()
            if not key:
                raise WorkflowValidationError("Compensation effect reference is required.")
            config = {"effectStepKey": key}
        elif item.step_type is WorkflowStepType.HUMAN_APPROVAL:
            reason = str(config.get("reasonCode", "workflow_gate")).strip()
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", reason):
                raise WorkflowValidationError("Approval reason is invalid.")
            config = {"reasonCode": reason}
        return config

    @staticmethod
    def _validate_dag(dependencies: dict[str, tuple[str, ...]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise WorkflowValidationError("Workflow dependencies contain a cycle.")
            if key in visited:
                return
            visiting.add(key)
            for dependency in dependencies[key]:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in sorted(dependencies):
            visit(key)

    async def _persist_version(
        self,
        *,
        definition: ControlledWorkflowDefinition,
        version_id: uuid.UUID,
        version_number: int,
        idempotency_key: str,
        normalized: dict[str, object],
        step_values: tuple[dict[str, object], ...],
        request: WorkflowVersionInput,
        supersedes_version_id: uuid.UUID | None,
        trace_id: uuid.UUID,
    ) -> ControlledWorkflowVersion:
        version = ControlledWorkflowVersion(
            version_id=version_id,
            definition_id=definition.definition_id,
            user_id=definition.user_id,
            workspace_id=definition.workspace_id,
            canvas_id=definition.canvas_id,
            version_number=version_number,
            schema_version=WORKFLOW_SCHEMA_VERSION,
            input_schema_version=request.input_schema_version,
            output_schema_version=request.output_schema_version,
            idempotency_key=idempotency_key,
            content_digest=_digest(normalized),
            normalized_definition=normalized,
            max_steps=len(step_values),
            max_duration_seconds=request.max_duration_seconds,
            max_retries_per_step=request.max_retries_per_step,
            compensation_policy=request.compensation_policy,
            supersedes_version_id=supersedes_version_id,
            created_by_user_id=definition.user_id,
            trace_id=trace_id,
            created_at=self.now,
        )
        self.session.add(version)
        await self.session.flush()
        key_to_id = {
            cast(str, item["stepKey"]): uuid.uuid5(version_id, f"step:{cast(str, item['stepKey'])}")
            for item in step_values
        }
        for item in step_values:
            step_key = cast(str, item["stepKey"])
            self.session.add(
                ControlledWorkflowStep(
                    step_id=key_to_id[step_key],
                    version_id=version_id,
                    user_id=definition.user_id,
                    workspace_id=definition.workspace_id,
                    canvas_id=definition.canvas_id,
                    step_key=step_key,
                    ordinal=cast(int, item["ordinal"]),
                    step_type=cast(str, item["stepType"]),
                    capability=cast(str, item["capability"]),
                    risk_class=cast(str, item["riskClass"]),
                    approval_required=cast(bool, item["approvalRequired"]),
                    max_attempts=cast(int, item["maxAttempts"]),
                    config=cast(dict[str, object], item["config"]),
                    step_digest=cast(str, item["stepDigest"]),
                    compensation_step_key=cast(str | None, item["compensationStepKey"]),
                )
            )
        await self.session.flush()
        for item in step_values:
            step_key = cast(str, item["stepKey"])
            for dependency_key in cast(list[str], item["dependsOn"]):
                self.session.add(
                    ControlledWorkflowDependency(
                        dependency_id=uuid.uuid5(
                            version_id, f"dependency:{step_key}:{dependency_key}"
                        ),
                        version_id=version_id,
                        step_id=key_to_id[step_key],
                        depends_on_step_id=key_to_id[dependency_key],
                    )
                )
        await self.session.flush()
        return version

    async def _assert_persisted_plan(self, version: ControlledWorkflowVersion) -> None:
        steps = await self._steps(version.version_id)
        dependencies = await self._dependencies(version.version_id)
        plan_steps = cast(list[dict[str, object]], version.normalized_definition.get("steps"))
        if len(steps) != len(plan_steps) or len(steps) != version.max_steps:
            raise WorkflowConflictError()
        id_to_key = {item.step_id: item.step_key for item in steps}
        dependency_keys = {
            (id_to_key[item.step_id], id_to_key[item.depends_on_step_id]) for item in dependencies
        }
        normalized_dependencies = {
            (cast(str, item["stepKey"]), dependency)
            for item in plan_steps
            for dependency in cast(list[str], item["dependsOn"])
        }
        if dependency_keys != normalized_dependencies:
            raise WorkflowConflictError()
        if _digest(version.normalized_definition) != version.content_digest:
            raise WorkflowConflictError()

    def _compile_plan(
        self,
        version: ControlledWorkflowVersion,
        steps: list[ControlledWorkflowStep],
        dependencies: list[ControlledWorkflowDependency],
    ) -> dict[str, object]:
        by_id = {item.step_id: item.step_key for item in steps}
        deps: dict[uuid.UUID, list[str]] = {}
        for item in dependencies:
            deps.setdefault(item.step_id, []).append(by_id[item.depends_on_step_id])
        return {
            "schemaVersion": PLAN_SCHEMA_VERSION,
            "workflowVersionId": str(version.version_id),
            "workflowVersionDigest": version.content_digest,
            "steps": [
                {
                    "stepId": str(item.step_id),
                    "stepKey": item.step_key,
                    "ordinal": item.ordinal,
                    "stepType": item.step_type,
                    "dependsOn": sorted(deps.get(item.step_id, [])),
                    "capability": item.capability,
                    "riskClass": item.risk_class,
                    "approvalRequired": item.approval_required,
                    "maxAttempts": item.max_attempts,
                    "stepDigest": item.step_digest,
                    "compensationStepKey": item.compensation_step_key,
                }
                for item in sorted(steps, key=lambda value: (value.ordinal, str(value.step_id)))
            ],
            "compensationPolicy": version.compensation_policy,
            "maxDurationSeconds": version.max_duration_seconds,
        }

    async def _workflow_output(self, execution: ControlledWorkflowExecution) -> dict[str, object]:
        rows = (
            await self.session.execute(
                select(ControlledWorkflowStepExecution, ControlledWorkflowStep)
                .join(
                    ControlledWorkflowStep,
                    ControlledWorkflowStep.step_id
                    == ControlledWorkflowStepExecution.step_definition_id,
                )
                .where(
                    ControlledWorkflowStepExecution.workflow_execution_id == execution.execution_id
                )
                .order_by(ControlledWorkflowStep.ordinal)
            )
        ).all()
        retrieval: GraphRetrievalRun | None = None
        grounded_response: str | None = None
        references: list[dict[str, object]] = []
        citation_ids: list[str] = []
        bundle_id: str | None = None
        effects: list[dict[str, object]] = []
        compensations: list[dict[str, object]] = []
        for row, step in rows:
            output = row.output or {}
            step_type = WorkflowStepType(step.step_type)
            if row.retrieval_id is not None:
                retrieval = await self.session.get(GraphRetrievalRun, row.retrieval_id)
            if step_type is WorkflowStepType.GROUNDED_MODEL and isinstance(output.get("text"), str):
                grounded_response = cast(str, output["text"])
                citation_ids = cast(list[str], output.get("citationIds", []))
            if step_type is WorkflowStepType.RENDER_CITATIONS:
                references = cast(list[dict[str, object]], output.get("citations", []))
            if row.bundle_id is not None:
                bundle_id = str(row.bundle_id)
            if row.effect_id is not None:
                effects.append(output)
            if row.rollback_result_id is not None:
                compensations.append(output)
        outcome = (
            WorkflowOutcome(retrieval.outcome)
            if retrieval is not None
            else (WorkflowOutcome.EFFECT_COMMITTED if effects else WorkflowOutcome.SUPPORTED)
        )
        if compensations:
            outcome = WorkflowOutcome.COMPENSATED
        return {
            "schemaVersion": OUTPUT_SCHEMA_VERSION,
            "workflowDefinitionId": str(execution.definition_id),
            "workflowVersionId": str(execution.version_id),
            "workflowExecutionId": str(execution.execution_id),
            "outcome": outcome.value,
            "groundedResponse": grounded_response,
            "retrievalId": str(retrieval.retrieval_id) if retrieval else None,
            "evidenceSufficiency": retrieval.outcome if retrieval else None,
            "contradiction": retrieval.outcome == "conflicting_evidence" if retrieval else False,
            "bounded": retrieval.outcome == "bounded_result" if retrieval else False,
            "citationIds": citation_ids,
            "references": references,
            "evidenceBundleId": bundle_id,
            "effects": effects,
            "compensations": compensations,
            "traceId": str(execution.trace_id),
            "completedAt": self.now.isoformat(),
        }

    async def _latest_retrieval(self, execution: ControlledWorkflowExecution) -> RetrievalRecord:
        retrieval_id = await self.session.scalar(
            select(ControlledWorkflowStepExecution.retrieval_id)
            .join(
                ControlledWorkflowStep,
                ControlledWorkflowStep.step_id
                == ControlledWorkflowStepExecution.step_definition_id,
            )
            .where(
                ControlledWorkflowStepExecution.workflow_execution_id == execution.execution_id,
                ControlledWorkflowStepExecution.retrieval_id.is_not(None),
            )
            .order_by(ControlledWorkflowStep.ordinal.desc())
            .limit(1)
        )
        if retrieval_id is None:
            raise _StepFailure(WorkflowFailureClass.EVIDENCE, "retrieval_evidence_missing")
        return await GraphAwareRetrievalService(
            self.session,
            embedding_provider=self.embedding_provider,
        ).get_owned(
            user_id=execution.user_id,
            workspace_id=execution.workspace_id,
            canvas_id=execution.canvas_id,
            retrieval_id=retrieval_id,
        )

    async def _effect_for_compensation(
        self,
        execution: ControlledWorkflowExecution,
        step: ControlledWorkflowStep,
    ) -> Any:
        effect_step_key = cast(str, step.config.get("effectStepKey"))
        effect = await self.session.scalar(
            select(ControlledWorkflowStepExecution)
            .join(
                ControlledWorkflowStep,
                ControlledWorkflowStep.step_id
                == ControlledWorkflowStepExecution.step_definition_id,
            )
            .where(
                ControlledWorkflowStepExecution.workflow_execution_id == execution.execution_id,
                ControlledWorkflowStep.step_key == effect_step_key,
                ControlledWorkflowStepExecution.effect_id.is_not(None),
            )
        )
        if effect is None or effect.effect_id is None:
            raise _StepFailure(WorkflowFailureClass.VALIDATION, "compensation_effect_missing")
        from opencanvas_api.db.models import ControlledAgentReversibleWriteEffect

        row = await self.session.get(ControlledAgentReversibleWriteEffect, effect.effect_id)
        if row is None:
            raise _StepFailure(WorkflowFailureClass.EVIDENCE, "effect_evidence_missing")
        return row

    async def _approval_available(self, row: ControlledWorkflowStepExecution) -> bool:
        if row.approval_id is None:
            return False
        approval = await self.session.get(ControlledAgentApproval, row.approval_id)
        return approval is not None and approval.decision == ApprovalDecision.APPROVED.value

    async def _deny_controlled_approval(
        self,
        *,
        execution_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> None:
        grant_row = await self.session.scalar(
            select(ControlledAgentCapabilityGrant).where(
                ControlledAgentCapabilityGrant.execution_id == execution_id,
                ControlledAgentCapabilityGrant.user_id == user_id,
                ControlledAgentCapabilityGrant.workspace_id == workspace_id,
            )
        )
        if grant_row is None:
            raise WorkflowAuthorityError()
        grant = ControlledAgentRepository._load_contract(
            CapabilityGrant, grant_row.payload, grant_row.payload_digest
        )
        if grant.approval_id is None:
            raise WorkflowAuthorityError()
        await self.agent_repository.append_approval(
            ApprovalRecord(
                approval_id=grant.approval_id,
                session_id=session_id,
                policy_version=grant.policy_version,
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                grant_id=grant.grant_id,
                decision=ApprovalDecision.DENIED,
                capabilities=grant.capabilities,
                resources=grant.resources,
                context_digest=grant.context_digest,
                plan_digest=grant.plan_digest,
                decided_at=self.now,
                expires_at=grant.expires_at,
            ),
            grant,
        )
        await self.agent_repository.append_state(
            ExecutionStateRecord(
                state_id=uuid.uuid4(),
                execution_id=execution_id,
                user_id=user_id,
                workspace_id=workspace_id,
                status=ExecutionStatus.DENIED,
                recorded_at=self.now,
                safe_reason_code="approval_denied",
            )
        )

    async def _append_step_audit(
        self,
        execution: ControlledWorkflowExecution,
        row: ControlledWorkflowStepExecution,
        trace_id: uuid.UUID,
        event_type: str,
        attributes: tuple[AuditAttribute, ...],
    ) -> uuid.UUID | None:
        if row.controlled_execution_id is None:
            return None
        event_id = uuid.uuid4()
        await self.agent_repository.append_audit_event(
            AuditEvent(
                event_id=event_id,
                trace_id=trace_id,
                execution_id=row.controlled_execution_id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                event_type=event_type,
                recorded_at=self.now,
                attributes=attributes,
            )
        )
        return event_id

    async def _evidence(
        self,
        execution: ControlledWorkflowExecution,
        row: ControlledWorkflowStepExecution,
        kind: str,
        evidence_id: uuid.UUID,
        evidence_digest: str,
        trace_id: uuid.UUID,
        audit_event_id: uuid.UUID | None,
    ) -> None:
        existing = await self.session.scalar(
            select(ControlledWorkflowEvidenceLink).where(
                ControlledWorkflowEvidenceLink.workflow_execution_id == execution.execution_id,
                ControlledWorkflowEvidenceLink.step_execution_id == row.step_execution_id,
                ControlledWorkflowEvidenceLink.evidence_kind == kind,
                ControlledWorkflowEvidenceLink.evidence_id == evidence_id,
            )
        )
        if existing is not None:
            if existing.evidence_digest != evidence_digest:
                raise WorkflowConflictError()
            return
        self.session.add(
            ControlledWorkflowEvidenceLink(
                evidence_link_id=uuid.uuid5(
                    row.step_execution_id, f"evidence:{kind}:{evidence_id}"
                ),
                workflow_execution_id=execution.execution_id,
                step_execution_id=row.step_execution_id,
                evidence_kind=kind,
                evidence_id=evidence_id,
                evidence_digest=evidence_digest,
                trace_id=trace_id,
                audit_event_id=audit_event_id,
                created_at=self.now,
            )
        )
        await self.session.flush()

    async def _version_state(
        self,
        version: ControlledWorkflowVersion,
        state: WorkflowVersionLifecycle,
        *,
        actor_user_id: uuid.UUID,
        trace_id: uuid.UUID,
        reason_code: str | None = None,
    ) -> ControlledWorkflowVersionState:
        latest = await self.session.scalar(
            select(ControlledWorkflowVersionState)
            .where(ControlledWorkflowVersionState.version_id == version.version_id)
            .order_by(ControlledWorkflowVersionState.sequence.desc())
            .limit(1)
        )
        previous = WorkflowVersionLifecycle(latest.state) if latest is not None else None
        if previous is None:
            if state is not WorkflowVersionLifecycle.DRAFT:
                raise WorkflowConflictError()
            sequence = 0
        else:
            if state not in VERSION_TRANSITIONS.get(previous, frozenset()):
                raise WorkflowConflictError()
            assert latest is not None
            sequence = latest.sequence + 1
        row = ControlledWorkflowVersionState(
            state_id=uuid.uuid4(),
            version_id=version.version_id,
            user_id=version.user_id,
            workspace_id=version.workspace_id,
            canvas_id=version.canvas_id,
            sequence=sequence,
            state=state.value,
            reason_code=reason_code,
            actor_user_id=actor_user_id,
            trace_id=trace_id,
            recorded_at=self.now,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _execution_transition(
        self,
        execution: ControlledWorkflowExecution,
        status: WorkflowExecutionStatus,
        *,
        from_status: WorkflowExecutionStatus | None,
        reason_code: str | None = None,
    ) -> None:
        current = WorkflowExecutionStatus(execution.status)
        if from_status is not None and current is not from_status:
            raise WorkflowConflictError()
        maximum = await self.session.scalar(
            select(func.max(ControlledWorkflowExecutionTransition.sequence)).where(
                ControlledWorkflowExecutionTransition.execution_id == execution.execution_id
            )
        )
        sequence = (maximum if maximum is not None else -1) + 1
        self.session.add(
            ControlledWorkflowExecutionTransition(
                transition_id=uuid.uuid4(),
                execution_id=execution.execution_id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                sequence=sequence,
                from_status=from_status.value if from_status else None,
                to_status=status.value,
                reason_code=reason_code,
                trace_id=execution.trace_id,
                recorded_at=self.now,
            )
        )
        execution.status = status.value
        await self.session.flush()

    async def _execution_transition_if_needed(
        self,
        execution: ControlledWorkflowExecution,
        status: WorkflowExecutionStatus,
    ) -> None:
        current = WorkflowExecutionStatus(execution.status)
        if current is status:
            return
        await self._execution_transition(execution, status, from_status=current)

    async def _step_transition(
        self,
        row: ControlledWorkflowStepExecution,
        status: WorkflowStepStatus,
        *,
        from_status: WorkflowStepStatus | None,
        reason_code: str | None = None,
    ) -> None:
        current = WorkflowStepStatus(row.status)
        if from_status is not None and current not in {from_status, status}:
            raise WorkflowConflictError()
        maximum = await self.session.scalar(
            select(func.max(ControlledWorkflowStepTransition.sequence)).where(
                ControlledWorkflowStepTransition.step_execution_id == row.step_execution_id
            )
        )
        sequence = (maximum if maximum is not None else -1) + 1
        self.session.add(
            ControlledWorkflowStepTransition(
                transition_id=uuid.uuid4(),
                step_execution_id=row.step_execution_id,
                sequence=sequence,
                from_status=from_status.value if from_status else None,
                to_status=status.value,
                reason_code=reason_code,
                trace_id=uuid.uuid5(
                    row.workflow_execution_id,
                    f"step-transition:{row.step_execution_id}:{sequence}",
                ),
                recorded_at=self.now,
            )
        )
        row.status = status.value
        await self.session.flush()

    async def _event(
        self,
        event_type: str,
        subject_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        trace_id: uuid.UUID,
        *,
        source: str,
        payload: dict[str, JsonValue],
        related_id: uuid.UUID | None = None,
        execution_id: uuid.UUID | None = None,
        audit_event_id: uuid.UUID | None = None,
    ) -> None:
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                subject_id=subject_id,
                related_id=related_id,
                actor_user_id=user_id,
                source_identity=f"{subject_id}:{source}"[:128],
                trace_id=trace_id,
                payload=payload,
                origin_type=(
                    "controlled_execution" if execution_id is not None else "authenticated_user"
                ),
                execution_id=execution_id,
                audit_event_id=audit_event_id,
            )
        )

    async def _scope(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
    ) -> Canvas:
        canvas = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.owner_id == user_id,
            )
        )
        if canvas is None:
            raise WorkflowNotFoundError()
        return canvas

    async def _selected_context(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        object_ids: tuple[uuid.UUID, ...],
    ) -> list[CanonicalObject]:
        await self._scope(user_id, workspace_id, canvas_id)
        rows = list(
            (
                await self.session.scalars(
                    select(CanonicalObject)
                    .where(
                        CanonicalObject.id.in_(object_ids),
                        CanonicalObject.workspace_id == workspace_id,
                        CanonicalObject.lifecycle_state == "created",
                    )
                    .order_by(CanonicalObject.id)
                )
            ).all()
        )
        if {item.id for item in rows} != set(object_ids):
            raise WorkflowAuthorityError()
        bindings = set(
            (
                await self.session.scalars(
                    select(CanonicalCanvasObjectBinding.object_id).where(
                        CanonicalCanvasObjectBinding.object_id.in_(object_ids),
                        CanonicalCanvasObjectBinding.canvas_id == canvas_id,
                        CanonicalCanvasObjectBinding.user_id == user_id,
                        CanonicalCanvasObjectBinding.workspace_id == workspace_id,
                    )
                )
            ).all()
        )
        if bindings != set(object_ids):
            raise WorkflowAuthorityError()
        return sorted(rows, key=lambda value: str(value.id))

    async def _owned_definition(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        definition_id: uuid.UUID,
    ) -> ControlledWorkflowDefinition:
        row = await self.session.scalar(
            select(ControlledWorkflowDefinition).where(
                ControlledWorkflowDefinition.definition_id == definition_id,
                ControlledWorkflowDefinition.user_id == user_id,
                ControlledWorkflowDefinition.workspace_id == workspace_id,
                ControlledWorkflowDefinition.canvas_id == canvas_id,
            )
        )
        if row is None:
            raise WorkflowNotFoundError()
        return row

    async def _owned_version(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> ControlledWorkflowVersion:
        row = await self.session.scalar(
            select(ControlledWorkflowVersion).where(
                ControlledWorkflowVersion.version_id == version_id,
                ControlledWorkflowVersion.user_id == user_id,
                ControlledWorkflowVersion.workspace_id == workspace_id,
                ControlledWorkflowVersion.canvas_id == canvas_id,
            )
        )
        if row is None:
            raise WorkflowNotFoundError()
        if _digest(row.normalized_definition) != row.content_digest:
            raise WorkflowConflictError()
        return row

    async def _versions(self, definition_id: uuid.UUID) -> list[ControlledWorkflowVersion]:
        return list(
            (
                await self.session.scalars(
                    select(ControlledWorkflowVersion)
                    .where(ControlledWorkflowVersion.definition_id == definition_id)
                    .order_by(
                        ControlledWorkflowVersion.version_number,
                        ControlledWorkflowVersion.version_id,
                    )
                )
            ).all()
        )

    async def _steps(self, version_id: uuid.UUID) -> list[ControlledWorkflowStep]:
        return list(
            (
                await self.session.scalars(
                    select(ControlledWorkflowStep)
                    .where(ControlledWorkflowStep.version_id == version_id)
                    .order_by(ControlledWorkflowStep.ordinal, ControlledWorkflowStep.step_id)
                )
            ).all()
        )

    async def _dependencies(self, version_id: uuid.UUID) -> list[ControlledWorkflowDependency]:
        return list(
            (
                await self.session.scalars(
                    select(ControlledWorkflowDependency)
                    .where(ControlledWorkflowDependency.version_id == version_id)
                    .order_by(
                        ControlledWorkflowDependency.step_id,
                        ControlledWorkflowDependency.depends_on_step_id,
                    )
                )
            ).all()
        )

    async def _latest_version_state(self, version_id: uuid.UUID) -> WorkflowVersionLifecycle:
        value = await self.session.scalar(
            select(ControlledWorkflowVersionState.state)
            .where(ControlledWorkflowVersionState.version_id == version_id)
            .order_by(ControlledWorkflowVersionState.sequence.desc())
            .limit(1)
        )
        if value is None:
            raise WorkflowConflictError()
        return WorkflowVersionLifecycle(value)

    async def _active_version(self, definition_id: uuid.UUID) -> ControlledWorkflowVersion | None:
        versions = await self._versions(definition_id)
        for version in reversed(versions):
            if (
                await self._latest_version_state(version.version_id)
                is WorkflowVersionLifecycle.ACTIVE
            ):
                return version
        return None

    @staticmethod
    def _validate_idempotency(value: str) -> None:
        if not IDEMPOTENCY_PATTERN.fullmatch(value):
            raise WorkflowValidationError("Workflow idempotency key is invalid.")

    @staticmethod
    def _classify_failure(error: Exception) -> WorkflowFailureClass:
        if isinstance(error, _StepFailure):
            return error.failure
        if isinstance(error, AIProviderError):
            return WorkflowFailureClass.RETRYABLE_PROVIDER
        if isinstance(error, GraphRetrievalError):
            return WorkflowFailureClass.EVIDENCE
        if isinstance(error, (OperationalError, WorkflowStorageError)):
            return WorkflowFailureClass.RETRYABLE_INTERNAL
        if isinstance(error, WorkflowAuthorityError):
            return WorkflowFailureClass.AUTHORITY
        if isinstance(error, WorkflowValidationError):
            return WorkflowFailureClass.VALIDATION
        return WorkflowFailureClass.VALIDATION


def _grounded_source(citation: GraphRetrievalCitation) -> GroundedSource:
    locator = citation.locator
    return GroundedSource(
        source_id=str(citation.citation_id),
        chunk_id=citation.citation_id,
        document_id=citation.canonical_object_id,
        document_title=citation.source_title,
        text=citation.excerpt,
        page_number=(
            cast(int, locator["pageNumber"]) if isinstance(locator.get("pageNumber"), int) else None
        ),
        heading=(
            cast(str, locator["heading"]) if isinstance(locator.get("heading"), str) else None
        ),
        chunk_index=(
            cast(int, locator["chunkIndex"]) if isinstance(locator.get("chunkIndex"), int) else 0
        ),
        char_start=(
            cast(int, locator["charStart"]) if isinstance(locator.get("charStart"), int) else 0
        ),
        char_end=(
            cast(int, locator["charEnd"])
            if isinstance(locator.get("charEnd"), int)
            else len(citation.excerpt)
        ),
        score=1.0,
        document_version=citation.source_version,
    )


def _role_for_step(step_type: WorkflowStepType) -> AgentRole:
    if step_type in {
        WorkflowStepType.GRAPH_RETRIEVAL,
        WorkflowStepType.EVALUATE_EVIDENCE,
        WorkflowStepType.RENDER_CITATIONS,
        WorkflowStepType.EVIDENCE_BUNDLE,
    }:
        return AgentRole.EVIDENCE_VERIFIER
    if step_type is WorkflowStepType.GROUNDED_MODEL:
        return AgentRole.DRAFTING_ASSISTANT
    if step_type in {
        WorkflowStepType.HUMAN_APPROVAL,
        WorkflowStepType.CONTROLLED_EFFECT,
        WorkflowStepType.COMPENSATION,
    }:
        return AgentRole.CONTROLLED_ACTION_EXECUTOR
    return AgentRole.SOLAR_SYSTEM_RESEARCHER


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _run_hook(callback: Any | None) -> None:
    if callback is None:
        return
    result = callback()
    if hasattr(result, "__await__"):
        await result


__all__ = [
    "MAX_DEPENDENCIES_PER_STEP",
    "MAX_WORKFLOW_STEPS",
    "OUTPUT_SCHEMA_VERSION",
    "PLAN_SCHEMA_VERSION",
    "STEP_TYPE_REGISTRY",
    "CompensationOutcome",
    "ControlledWorkflowService",
    "CreateWorkflowDraft",
    "CreateWorkflowVersion",
    "StartWorkflow",
    "WorkflowAuthorityError",
    "WorkflowConflictError",
    "WorkflowDefinitionRecord",
    "WorkflowError",
    "WorkflowExecutionRecord",
    "WorkflowExecutionStatus",
    "WorkflowFailureClass",
    "WorkflowKind",
    "WorkflowNotFoundError",
    "WorkflowOutcome",
    "WorkflowStepInput",
    "WorkflowStepStatus",
    "WorkflowStepType",
    "WorkflowStorageError",
    "WorkflowValidationError",
    "WorkflowVersionInput",
    "WorkflowVersionLifecycle",
]
