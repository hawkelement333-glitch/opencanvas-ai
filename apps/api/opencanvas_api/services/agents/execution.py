from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    Canvas,
    CanvasNode,
    ControlledAgentAuditEvent,
    ControlledAgentRequestIdentity,
    Document,
    DocumentChunk,
    DocumentVersion,
    Workspace,
)
from opencanvas_api.services.agents.contracts import (
    SCHEMA_VERSION,
    ApprovalRecord,
    AuditAttribute,
    AuditEvent,
    Capability,
    CapabilityGrant,
    ContextSnapshot,
    ContractModel,
    Digest,
    ExecutionStateRecord,
    ExecutionStatus,
    PlanSnapshot,
    ResourceKind,
    ResourceScope,
    RiskClass,
    _require_aware_utc,
    contract_digest,
)
from opencanvas_api.services.agents.persistence import (
    AgentPersistenceNotFound,
    AgentStateConflict,
    AgentStateTransitionError,
    ApprovalConsumptionAttempt,
    ControlledAgentRepository,
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
    execution_id: uuid.UUID
    context_snapshot_id: uuid.UUID
    expected_context_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: uuid.UUID
    expected_plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    action: ControlledAction
    grant_id: uuid.UUID
    approval_id: uuid.UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    instruction: str = Field(
        default="Create a grounded draft from the selected evidence.",
        min_length=1,
        max_length=8_000,
    )
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=64)

    @field_validator("idempotency_key", "client_request_id", "correlation_id")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("request identifiers must not contain surrounding whitespace")
        return value

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("instruction must not be blank")
        return normalized


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
    execution_id: uuid.UUID
    action: ControlledAction
    idempotency_key: str
    instruction: str
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
            execution_id=request.execution_id,
            action=request.action,
            idempotency_key=request.idempotency_key,
            instruction=request.instruction,
            context_snapshot_id=request.context_snapshot_id,
            context_digest=request.expected_context_digest,
            plan_id=request.plan_id,
            plan_digest=request.expected_plan_digest,
            grant_id=request.grant_id,
            approval_id=request.approval_id,
        )
    )


class AuthorityPreflightDenied(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class IdempotencyConflict(RuntimeError):
    pass


class IdempotencyPersistenceConflict(RuntimeError):
    pass


class ImmutableContextDenied(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ResolvedContextResource(ContractModel):
    """Exact untrusted evidence resolved from one approved selected-context resource."""

    contract_kind: Literal["resolved_context_resource"] = "resolved_context_resource"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    scope: ResourceScope
    canvas_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    document_id: uuid.UUID | None = None
    document_version: int | None = Field(default=None, ge=1)
    untrusted_content: Literal[True] = True


@dataclass(frozen=True, slots=True)
class ResolvedSelectedContext:
    snapshot_id: uuid.UUID
    context_digest: Digest
    resolution_digest: Digest
    resources: tuple[ResolvedContextResource, ...]


def resolved_resource_digest(resource: ResolvedContextResource) -> Digest:
    return contract_digest(resource)


def resolved_context_digest(
    *,
    snapshot_id: uuid.UUID,
    context_digest: Digest,
    resources: tuple[ResolvedContextResource, ...],
) -> Digest:
    class ResolutionEnvelope(ContractModel):
        contract_kind: Literal["resolved_selected_context"] = "resolved_selected_context"
        schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
        snapshot_id: uuid.UUID
        context_digest: Digest
        resources: tuple[ResolvedContextResource, ...]

    return contract_digest(
        ResolutionEnvelope(
            snapshot_id=snapshot_id,
            context_digest=context_digest,
            resources=resources,
        )
    )


@dataclass(frozen=True, slots=True)
class RequestReservation:
    request_identity_id: uuid.UUID
    execution_id: uuid.UUID
    request_digest: Digest
    created: bool


class ExecutionRequestRegistry:
    """Reserve one append-only logical request identity using database uniqueness."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)

    async def reserve(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        request: ControlledExecutionRequest,
        created_at: datetime,
    ) -> RequestReservation:
        if authenticated_user_id != request.user_id:
            raise AuthorityPreflightDenied("user_scope_mismatch")
        digest = idempotency_digest(request)
        identity_id = uuid.uuid4()
        try:
            async with self.session.begin_nested():
                self.session.add(
                    ControlledAgentRequestIdentity(
                        request_identity_id=identity_id,
                        execution_id=request.execution_id,
                        user_id=authenticated_user_id,
                        workspace_id=request.workspace_id,
                        canvas_id=request.canvas_id,
                        action=request.action.value,
                        idempotency_key=request.idempotency_key,
                        request_digest=digest,
                        created_at=created_at,
                    )
                )
                await self.session.flush()
            return RequestReservation(identity_id, request.execution_id, digest, True)
        except IntegrityError:
            existing = await self.session.scalar(
                select(ControlledAgentRequestIdentity).where(
                    ControlledAgentRequestIdentity.user_id == authenticated_user_id,
                    ControlledAgentRequestIdentity.workspace_id == request.workspace_id,
                    ControlledAgentRequestIdentity.canvas_id == request.canvas_id,
                    ControlledAgentRequestIdentity.action == request.action.value,
                    ControlledAgentRequestIdentity.idempotency_key == request.idempotency_key,
                )
            )
            if existing is None:
                raise IdempotencyPersistenceConflict("request_identity_unavailable") from None
            if existing.request_digest != digest:
                await self.repository.append_audit_event(
                    AuditEvent(
                        event_id=uuid.uuid4(),
                        trace_id=uuid.uuid4(),
                        execution_id=existing.execution_id,
                        user_id=existing.user_id,
                        workspace_id=existing.workspace_id,
                        event_type="execution.idempotency_conflict",
                        recorded_at=created_at,
                        attributes=(AuditAttribute(key="category", value="request_conflict"),),
                    )
                )
                raise IdempotencyConflict("idempotency_conflict") from None
            return RequestReservation(
                existing.request_identity_id,
                existing.execution_id,
                existing.request_digest,
                False,
            )


@dataclass(frozen=True, slots=True)
class AuthorizedPreflight:
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    action: ControlledAction
    context_snapshot_id: uuid.UUID
    context_digest: Digest
    plan_id: uuid.UUID
    plan_digest: Digest
    grant_id: uuid.UUID
    approval_id: uuid.UUID
    approval_consumption_id: uuid.UUID
    policy_decision_id: uuid.UUID
    correlation_id: str


class ExecutionAuthorityPreflight:
    """Authorize one stored execution without provider calls, retrieval, or workspace effects."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)

    async def authorize(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        request: ControlledExecutionRequest,
        evaluated_at: datetime,
    ) -> AuthorizedPreflight:
        if authenticated_user_id != request.user_id:
            raise AuthorityPreflightDenied("user_scope_mismatch")
        boundary = ACTION_REGISTRY.get(request.action)
        if boundary is None:
            raise AuthorityPreflightDenied("action_unknown")
        canvas = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == request.canvas_id,
                Canvas.workspace_id == request.workspace_id,
                Workspace.owner_id == authenticated_user_id,
                Workspace.deleted_at.is_(None),
                Workspace.lifecycle_state != "deleted",
            )
        )
        if canvas is None:
            raise AuthorityPreflightDenied("canvas_scope_mismatch")
        try:
            inspection = await self.repository.inspect_execution(
                user_id=authenticated_user_id,
                workspace_id=request.workspace_id,
                execution_id=request.execution_id,
                limit=100,
                offset=0,
            )
        except AgentPersistenceNotFound as exc:
            raise AuthorityPreflightDenied("authority_not_found") from exc
        execution = inspection.execution
        approval = next(
            (row for row in inspection.approvals if row.approval_id == request.approval_id), None
        )
        if (
            execution.context_snapshot_id != request.context_snapshot_id
            or inspection.context.payload_digest != request.expected_context_digest
        ):
            raise AuthorityPreflightDenied("context_hash_mismatch")
        if (
            execution.plan_id != request.plan_id
            or inspection.plan.payload_digest != request.expected_plan_digest
        ):
            raise AuthorityPreflightDenied("plan_hash_mismatch")
        if execution.grant_id != request.grant_id:
            raise AuthorityPreflightDenied("grant_scope_mismatch")
        if request.approval_id is None or approval is None:
            raise AuthorityPreflightDenied("approval_missing")

        capability = Capability.DRAFT_ANSWER_CREATE
        resource = ResourceScope(kind=ResourceKind.CANVAS, resource_id=request.canvas_id)
        plan = self.repository._load_contract(
            PlanSnapshot, inspection.plan.payload, inspection.plan.payload_digest
        )
        matching = tuple(
            action
            for action in plan.actions
            if action.capability is capability and action.resource == resource
        )
        if not matching:
            raise AuthorityPreflightDenied("action_scope_mismatch")
        if any(
            action.risk_class not in {RiskClass.R0_OBSERVATION, RiskClass.R1_DRAFT}
            for action in matching
        ):
            raise AuthorityPreflightDenied("risk_scope_mismatch")

        consumption_id = uuid.uuid4()
        decision_id = uuid.uuid4()
        decision = await self.repository.consume_approval(
            ApprovalConsumptionAttempt(
                consumption_id=consumption_id,
                decision_id=decision_id,
                user_id=authenticated_user_id,
                workspace_id=request.workspace_id,
                execution_id=request.execution_id,
                approval_id=request.approval_id,
                capability=capability,
                resource=resource,
                evaluated_at=evaluated_at,
            )
        )
        if decision.outcome.value != "allow":
            raise AuthorityPreflightDenied(decision.reason_code)
        return AuthorizedPreflight(
            execution_id=request.execution_id,
            user_id=authenticated_user_id,
            workspace_id=request.workspace_id,
            canvas_id=request.canvas_id,
            action=request.action,
            context_snapshot_id=request.context_snapshot_id,
            context_digest=request.expected_context_digest,
            plan_id=request.plan_id,
            plan_digest=request.expected_plan_digest,
            grant_id=request.grant_id,
            approval_id=request.approval_id,
            approval_consumption_id=consumption_id,
            policy_decision_id=decision_id,
            correlation_id=request.correlation_id,
        )


class ImmutableSelectedContextResolver:
    """Resolve only the exact stored selection at the approved execution boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)

    async def resolve(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        authorized: AuthorizedPreflight,
    ) -> ResolvedSelectedContext:
        if authenticated_user_id != authorized.user_id:
            raise ImmutableContextDenied("user_scope_mismatch")
        try:
            inspection = await self.repository.inspect_execution(
                user_id=authenticated_user_id,
                workspace_id=authorized.workspace_id,
                execution_id=authorized.execution_id,
                limit=100,
                offset=0,
            )
        except AgentPersistenceNotFound as exc:
            raise ImmutableContextDenied("context_not_found") from exc
        if (
            inspection.execution.context_snapshot_id != authorized.context_snapshot_id
            or inspection.context.snapshot_id != authorized.context_snapshot_id
            or inspection.context.payload_digest != authorized.context_digest
        ):
            raise ImmutableContextDenied("context_identity_mismatch")
        context = self.repository._load_contract(
            ContextSnapshot,
            inspection.context.payload,
            inspection.context.payload_digest,
        )
        expected_scope = (
            authorized.user_id,
            authorized.workspace_id,
            authorized.execution_id,
        )
        if expected_scope != (context.user_id, context.workspace_id, context.execution_id):
            raise ImmutableContextDenied("context_scope_mismatch")
        scopes = tuple(resource.scope for resource in context.resources)
        if len(scopes) != len(set(scopes)):
            raise ImmutableContextDenied("context_duplicate_resource")

        resolved = tuple(
            [
                await self._resolve_resource(
                    authorized=authorized,
                    scope=resource.scope,
                    expected_digest=resource.content_digest,
                )
                for resource in context.resources
            ]
        )
        return ResolvedSelectedContext(
            snapshot_id=context.snapshot_id,
            context_digest=inspection.context.payload_digest,
            resolution_digest=resolved_context_digest(
                snapshot_id=context.snapshot_id,
                context_digest=inspection.context.payload_digest,
                resources=resolved,
            ),
            resources=resolved,
        )

    async def _resolve_resource(
        self,
        *,
        authorized: AuthorizedPreflight,
        scope: ResourceScope,
        expected_digest: Digest,
    ) -> ResolvedContextResource:
        if scope.version is None:
            raise ImmutableContextDenied("context_version_missing")
        resource: ResolvedContextResource
        if scope.kind is ResourceKind.CANVAS:
            row = await self.session.scalar(
                select(Canvas)
                .join(Workspace, Workspace.id == Canvas.workspace_id)
                .where(
                    Canvas.id == scope.resource_id,
                    Canvas.id == authorized.canvas_id,
                    Canvas.workspace_id == authorized.workspace_id,
                    Canvas.revision == scope.version,
                    Workspace.owner_id == authorized.user_id,
                    Workspace.deleted_at.is_(None),
                    Workspace.lifecycle_state != "deleted",
                )
            )
            if row is None:
                raise ImmutableContextDenied("context_resource_missing")
            resource = ResolvedContextResource(
                scope=scope,
                canvas_id=row.id,
                title=row.name,
                content=f"Canvas revision {row.revision}",
            )
        elif scope.kind is ResourceKind.NODE:
            row = await self.session.scalar(
                select(CanvasNode)
                .join(Canvas, Canvas.id == CanvasNode.canvas_id)
                .join(Workspace, Workspace.id == Canvas.workspace_id)
                .where(
                    CanvasNode.id == scope.resource_id,
                    CanvasNode.canvas_id == authorized.canvas_id,
                    CanvasNode.revision == scope.version,
                    Canvas.workspace_id == authorized.workspace_id,
                    Workspace.owner_id == authorized.user_id,
                    Workspace.deleted_at.is_(None),
                    Workspace.lifecycle_state != "deleted",
                )
            )
            if row is None:
                raise ImmutableContextDenied("context_resource_missing")
            resource = ResolvedContextResource(
                scope=scope,
                canvas_id=row.canvas_id,
                title=row.title,
                content=row.text,
            )
        elif scope.kind is ResourceKind.DOCUMENT_VERSION:
            row = await self.session.scalar(
                select(DocumentVersion)
                .join(Document, Document.id == DocumentVersion.document_id)
                .join(Canvas, Canvas.id == Document.canvas_id)
                .join(Workspace, Workspace.id == Canvas.workspace_id)
                .where(
                    DocumentVersion.id == scope.resource_id,
                    DocumentVersion.version == scope.version,
                    DocumentVersion.deleted_at.is_(None),
                    DocumentVersion.status == "ready",
                    Document.canvas_id == authorized.canvas_id,
                    Document.deleted_at.is_(None),
                    Document.status == "ready",
                    Canvas.workspace_id == authorized.workspace_id,
                    Workspace.owner_id == authorized.user_id,
                    Workspace.deleted_at.is_(None),
                    Workspace.lifecycle_state != "deleted",
                )
            )
            if row is None or not row.extracted_text:
                raise ImmutableContextDenied("context_resource_missing")
            resource = ResolvedContextResource(
                scope=scope,
                canvas_id=authorized.canvas_id,
                title=row.file_name,
                content=row.extracted_text,
                document_id=row.document_id,
                document_version=row.version,
            )
        elif scope.kind is ResourceKind.CHUNK:
            row = await self.session.scalar(
                select(DocumentChunk)
                .join(Document, Document.id == DocumentChunk.document_id)
                .join(Canvas, Canvas.id == Document.canvas_id)
                .join(Workspace, Workspace.id == Canvas.workspace_id)
                .where(
                    DocumentChunk.id == scope.resource_id,
                    DocumentChunk.document_version == scope.version,
                    Document.canvas_id == authorized.canvas_id,
                    Document.deleted_at.is_(None),
                    Document.status == "ready",
                    Canvas.workspace_id == authorized.workspace_id,
                    Workspace.owner_id == authorized.user_id,
                    Workspace.deleted_at.is_(None),
                    Workspace.lifecycle_state != "deleted",
                )
            )
            if row is None:
                raise ImmutableContextDenied("context_resource_missing")
            resource = ResolvedContextResource(
                scope=scope,
                canvas_id=authorized.canvas_id,
                title=row.heading or f"Chunk {row.chunk_index + 1}",
                content=row.content,
                document_id=row.document_id,
                document_version=row.document_version,
            )
        else:
            raise ImmutableContextDenied("context_resource_kind_unsupported")

        if resolved_resource_digest(resource) != expected_digest:
            raise ImmutableContextDenied("context_content_hash_mismatch")
        return resource


class CancellationRequest(ContractModel):
    cancellation_id: uuid.UUID
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    requested_at: datetime
    reason_code: str = Field(default="user_cancelled", min_length=1, max_length=64)
    replacement_execution_id: uuid.UUID | None = None

    _requested_at_is_utc = field_validator("requested_at")(_require_aware_utc)


@dataclass(frozen=True, slots=True)
class CancellationOutcome:
    cancelled: bool
    duplicate: bool
    status: ExecutionStatus
    reason_code: str


class ResultAcceptanceRequest(ContractModel):
    delivery_id: uuid.UUID
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    running_state_id: uuid.UUID
    context_snapshot_id: uuid.UUID
    context_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    resolution_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    result_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    produced_at: datetime

    _produced_at_is_utc = field_validator("produced_at")(_require_aware_utc)


@dataclass(frozen=True, slots=True)
class ResultAcceptanceOutcome:
    accepted: bool
    duplicate: bool
    status: ExecutionStatus
    reason_code: str


def _database_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ControlledExecutionLifecycle:
    """Authoritative cancellation and result-publication boundary for synchronous execution."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)

    async def cancel(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        request: CancellationRequest,
        trace_id: uuid.UUID,
    ) -> CancellationOutcome:
        if authenticated_user_id != request.user_id:
            raise AuthorityPreflightDenied("user_scope_mismatch")
        existing = await self.session.get(ControlledAgentAuditEvent, request.cancellation_id)
        if existing is not None:
            if (
                existing.execution_id != request.execution_id
                or existing.user_id != request.user_id
                or existing.workspace_id != request.workspace_id
                or existing.event_type
                not in {
                    "execution.cancelled",
                    "execution.cancellation_rejected",
                }
            ):
                raise AuthorityPreflightDenied("cancellation_identity_conflict")
            status = await self._required_current_status(request)
            return CancellationOutcome(
                cancelled=existing.event_type == "execution.cancelled",
                duplicate=True,
                status=status,
                reason_code=self._attribute(existing, "reason") or request.reason_code,
            )

        current = await self.repository.current_state(
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            execution_id=request.execution_id,
        )
        if current is None:
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=request.execution_id,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                    status=ExecutionStatus.PROPOSED,
                    recorded_at=request.requested_at,
                    safe_reason_code="cancelled_before_start",
                )
            )
            current = await self.repository.current_state(
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                execution_id=request.execution_id,
            )
        if current is None:
            raise AgentStateConflict("execution_state_unavailable")
        current_status = ExecutionStatus(current.status)
        if current_status in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.DENIED,
        }:
            await self._append_lifecycle_event(
                event_id=request.cancellation_id,
                trace_id=trace_id,
                execution_id=request.execution_id,
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                event_type="execution.cancellation_rejected",
                recorded_at=request.requested_at,
                attributes=(
                    AuditAttribute(key="reason", value="execution_already_terminal"),
                    AuditAttribute(key="status", value=current_status.value),
                ),
            )
            return CancellationOutcome(
                cancelled=False,
                duplicate=False,
                status=current_status,
                reason_code="execution_already_terminal",
            )
        if current_status is ExecutionStatus.CANCELLED:
            await self._append_lifecycle_event(
                event_id=request.cancellation_id,
                trace_id=trace_id,
                execution_id=request.execution_id,
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                event_type="execution.cancelled",
                recorded_at=request.requested_at,
                attributes=(
                    AuditAttribute(key="reason", value=request.reason_code),
                    AuditAttribute(key="status", value=ExecutionStatus.CANCELLED.value),
                ),
            )
            return CancellationOutcome(
                cancelled=True,
                duplicate=False,
                status=ExecutionStatus.CANCELLED,
                reason_code=request.reason_code,
            )

        try:
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=request.execution_id,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                    status=ExecutionStatus.CANCELLED,
                    recorded_at=request.requested_at,
                    safe_reason_code=request.reason_code,
                )
            )
        except AgentStateConflict:
            current_status = await self._required_current_status(request)
            if current_status is not ExecutionStatus.CANCELLED:
                return await self._record_cancel_race_rejection(
                    request=request,
                    trace_id=trace_id,
                    status=current_status,
                )

        attributes = [
            AuditAttribute(key="reason", value=request.reason_code),
            AuditAttribute(key="status", value=ExecutionStatus.CANCELLED.value),
        ]
        if request.replacement_execution_id is not None:
            attributes.append(
                AuditAttribute(
                    key="replacementExecutionId",
                    value=str(request.replacement_execution_id),
                )
            )
        await self._append_lifecycle_event(
            event_id=request.cancellation_id,
            trace_id=trace_id,
            execution_id=request.execution_id,
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            event_type="execution.cancelled",
            recorded_at=request.requested_at,
            attributes=tuple(attributes),
        )
        return CancellationOutcome(
            cancelled=True,
            duplicate=False,
            status=ExecutionStatus.CANCELLED,
            reason_code=request.reason_code,
        )

    async def accept_result(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        authorized: AuthorizedPreflight,
        resolved: ResolvedSelectedContext,
        request: ResultAcceptanceRequest,
        accepted_at: datetime,
        trace_id: uuid.UUID,
    ) -> ResultAcceptanceOutcome:
        _require_aware_utc(accepted_at)
        self._validate_result_identity(
            authenticated_user_id=authenticated_user_id,
            authorized=authorized,
            resolved=resolved,
            request=request,
        )
        existing = await self.session.get(ControlledAgentAuditEvent, request.delivery_id)
        if existing is not None:
            return self._existing_result_outcome(existing, request)

        current = await self.repository.current_state(
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            execution_id=request.execution_id,
        )
        if current is None:
            return await self._reject_result(
                request=request,
                trace_id=trace_id,
                accepted_at=accepted_at,
                status=ExecutionStatus.PROPOSED,
                reason_code="execution_not_running",
            )
        current_status = ExecutionStatus(current.status)
        if current.state_id != request.running_state_id:
            return await self._reject_result(
                request=request,
                trace_id=trace_id,
                accepted_at=accepted_at,
                status=current_status,
                reason_code="stale_execution_state",
            )
        if current_status is not ExecutionStatus.RUNNING:
            return await self._reject_result(
                request=request,
                trace_id=trace_id,
                accepted_at=accepted_at,
                status=current_status,
                reason_code=f"execution_{current_status.value}",
            )

        authority_failure = await self._authority_failure(
            authorized=authorized,
            evaluated_at=accepted_at,
        )
        if authority_failure is not None:
            with suppress(AgentStateConflict):
                await self.repository.append_state(
                    ExecutionStateRecord(
                        state_id=uuid.uuid4(),
                        execution_id=request.execution_id,
                        user_id=request.user_id,
                        workspace_id=request.workspace_id,
                        status=ExecutionStatus.CANCELLED,
                        recorded_at=accepted_at,
                        safe_reason_code=authority_failure,
                    )
                )
            current_status = await self._required_current_status(request)
            return await self._reject_result(
                request=request,
                trace_id=trace_id,
                accepted_at=accepted_at,
                status=current_status,
                reason_code=authority_failure,
            )

        try:
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=request.execution_id,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                    status=ExecutionStatus.SUCCEEDED,
                    recorded_at=accepted_at,
                )
            )
        except (AgentStateConflict, AgentStateTransitionError):
            current_status = await self._required_current_status(request)
            return await self._reject_result(
                request=request,
                trace_id=trace_id,
                accepted_at=accepted_at,
                status=current_status,
                reason_code=f"execution_{current_status.value}",
            )

        await self._append_lifecycle_event(
            event_id=request.delivery_id,
            trace_id=trace_id,
            execution_id=request.execution_id,
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            event_type="execution.result_accepted",
            recorded_at=accepted_at,
            attributes=(
                AuditAttribute(key="resultDigest", value=request.result_digest),
                AuditAttribute(key="resolutionDigest", value=request.resolution_digest),
                AuditAttribute(key="status", value=ExecutionStatus.SUCCEEDED.value),
            ),
        )
        return ResultAcceptanceOutcome(
            accepted=True,
            duplicate=False,
            status=ExecutionStatus.SUCCEEDED,
            reason_code="result_accepted",
        )

    async def _authority_failure(
        self,
        *,
        authorized: AuthorizedPreflight,
        evaluated_at: datetime,
    ) -> str | None:
        inspection = await self.repository.inspect_execution(
            user_id=authorized.user_id,
            workspace_id=authorized.workspace_id,
            execution_id=authorized.execution_id,
            limit=100,
            offset=0,
        )
        grant_row = next(
            (row for row in inspection.grants if row.grant_id == authorized.grant_id),
            None,
        )
        approval_row = next(
            (row for row in inspection.approvals if row.approval_id == authorized.approval_id),
            None,
        )
        if grant_row is None or approval_row is None:
            return "authority_not_found"
        consumption = next(
            (
                row
                for row in inspection.consumptions
                if row.consumption_id == authorized.approval_consumption_id
            ),
            None,
        )
        decision = next(
            (
                row
                for row in inspection.policy_decisions
                if row.decision_id == authorized.policy_decision_id
            ),
            None,
        )
        if consumption is None or decision is None:
            return "authority_not_consumed"
        if (
            consumption.approval_id != authorized.approval_id
            or consumption.policy_decision_id != authorized.policy_decision_id
            or decision.outcome != "allow"
            or decision.approval_id != authorized.approval_id
            or decision.grant_id != authorized.grant_id
        ):
            return "authority_binding_mismatch"
        grant = self.repository._load_contract(
            CapabilityGrant,
            grant_row.payload,
            grant_row.payload_digest,
        )
        approval = self.repository._load_contract(
            ApprovalRecord,
            approval_row.payload,
            approval_row.payload_digest,
        )
        if evaluated_at < grant.issued_at or evaluated_at >= grant.expires_at:
            return "grant_inactive"
        if evaluated_at < approval.decided_at or evaluated_at >= approval.expires_at:
            return "approval_inactive"
        if any(
            row.grant_id == authorized.grant_id and _database_utc(row.revoked_at) <= evaluated_at
            for row in inspection.revocations
        ):
            return "grant_revoked"
        return None

    @staticmethod
    def _validate_result_identity(
        *,
        authenticated_user_id: uuid.UUID,
        authorized: AuthorizedPreflight,
        resolved: ResolvedSelectedContext,
        request: ResultAcceptanceRequest,
    ) -> None:
        if authenticated_user_id != request.user_id or authenticated_user_id != authorized.user_id:
            raise AuthorityPreflightDenied("user_scope_mismatch")
        if (
            request.execution_id != authorized.execution_id
            or request.workspace_id != authorized.workspace_id
            or request.context_snapshot_id != authorized.context_snapshot_id
            or request.context_digest != authorized.context_digest
            or request.context_snapshot_id != resolved.snapshot_id
            or request.context_digest != resolved.context_digest
            or request.resolution_digest != resolved.resolution_digest
        ):
            raise AuthorityPreflightDenied("result_identity_mismatch")

    @staticmethod
    def _attribute(event: ControlledAgentAuditEvent, key: str) -> str | None:
        value = next(
            (item.get("value") for item in event.attributes if item.get("key") == key),
            None,
        )
        return value if isinstance(value, str) else None

    def _existing_result_outcome(
        self,
        event: ControlledAgentAuditEvent,
        request: ResultAcceptanceRequest,
    ) -> ResultAcceptanceOutcome:
        if (
            event.execution_id != request.execution_id
            or event.user_id != request.user_id
            or event.workspace_id != request.workspace_id
            or self._attribute(event, "resultDigest") != request.result_digest
            or self._attribute(event, "resolutionDigest") != request.resolution_digest
        ):
            raise AuthorityPreflightDenied("result_delivery_conflict")
        status_value = self._attribute(event, "status") or ExecutionStatus.FAILED.value
        status = ExecutionStatus(status_value)
        return ResultAcceptanceOutcome(
            accepted=event.event_type == "execution.result_accepted",
            duplicate=True,
            status=status,
            reason_code=self._attribute(event, "reason") or event.event_type.rsplit(".", 1)[-1],
        )

    async def _reject_result(
        self,
        *,
        request: ResultAcceptanceRequest,
        trace_id: uuid.UUID,
        accepted_at: datetime,
        status: ExecutionStatus,
        reason_code: str,
    ) -> ResultAcceptanceOutcome:
        await self._append_lifecycle_event(
            event_id=request.delivery_id,
            trace_id=trace_id,
            execution_id=request.execution_id,
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            event_type="execution.result_rejected",
            recorded_at=accepted_at,
            attributes=(
                AuditAttribute(key="reason", value=reason_code),
                AuditAttribute(key="resultDigest", value=request.result_digest),
                AuditAttribute(key="resolutionDigest", value=request.resolution_digest),
                AuditAttribute(key="status", value=status.value),
            ),
        )
        return ResultAcceptanceOutcome(
            accepted=False,
            duplicate=False,
            status=status,
            reason_code=reason_code,
        )

    async def _required_current_status(
        self,
        request: CancellationRequest | ResultAcceptanceRequest,
    ) -> ExecutionStatus:
        current = await self.repository.current_state(
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            execution_id=request.execution_id,
        )
        if current is None:
            raise AgentStateConflict("execution_state_unavailable")
        return ExecutionStatus(current.status)

    async def _record_cancel_race_rejection(
        self,
        *,
        request: CancellationRequest,
        trace_id: uuid.UUID,
        status: ExecutionStatus,
    ) -> CancellationOutcome:
        await self._append_lifecycle_event(
            event_id=request.cancellation_id,
            trace_id=trace_id,
            execution_id=request.execution_id,
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            event_type="execution.cancellation_rejected",
            recorded_at=request.requested_at,
            attributes=(
                AuditAttribute(key="reason", value="execution_state_changed"),
                AuditAttribute(key="status", value=status.value),
            ),
        )
        return CancellationOutcome(
            cancelled=False,
            duplicate=False,
            status=status,
            reason_code="execution_state_changed",
        )

    async def _append_lifecycle_event(
        self,
        *,
        event_id: uuid.UUID,
        trace_id: uuid.UUID,
        execution_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        event_type: str,
        recorded_at: datetime,
        attributes: tuple[AuditAttribute, ...],
    ) -> None:
        await self.repository.append_audit_event(
            AuditEvent(
                event_id=event_id,
                trace_id=trace_id,
                execution_id=execution_id,
                user_id=user_id,
                workspace_id=workspace_id,
                event_type=event_type,
                recorded_at=recorded_at,
                attributes=attributes,
            )
        )


__all__ = [
    "ACTION_REGISTRY",
    "GROUND_DRAFT_STAGES",
    "ActionBoundary",
    "AuthorityPreflightDenied",
    "AuthorizedPreflight",
    "CancellationOutcome",
    "CancellationRequest",
    "ControlledAction",
    "ControlledExecutionLifecycle",
    "ControlledExecutionPlan",
    "ControlledExecutionRequest",
    "ExecutionAuthorityPreflight",
    "ExecutionRequestRegistry",
    "ExecutionStage",
    "IdempotencyConflict",
    "IdempotencyFingerprint",
    "IdempotencyPersistenceConflict",
    "ImmutableContextDenied",
    "ImmutableSelectedContextResolver",
    "RequestReservation",
    "ResolvedContextResource",
    "ResolvedSelectedContext",
    "ResultAcceptanceOutcome",
    "ResultAcceptanceRequest",
    "idempotency_digest",
    "resolved_context_digest",
    "resolved_resource_digest",
]
