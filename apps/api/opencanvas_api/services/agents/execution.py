from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
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
    ControlledAgentRequestIdentity,
    Document,
    DocumentChunk,
    DocumentVersion,
    Workspace,
)
from opencanvas_api.services.agents.contracts import (
    SCHEMA_VERSION,
    AuditAttribute,
    AuditEvent,
    Capability,
    ContextSnapshot,
    ContractModel,
    Digest,
    PlanSnapshot,
    ResourceKind,
    ResourceScope,
    RiskClass,
    _require_aware_utc,
    contract_digest,
)
from opencanvas_api.services.agents.persistence import (
    AgentPersistenceNotFound,
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
    execution_id: uuid.UUID
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
            execution_id=request.execution_id,
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


__all__ = [
    "ACTION_REGISTRY",
    "GROUND_DRAFT_STAGES",
    "ActionBoundary",
    "AuthorityPreflightDenied",
    "AuthorizedPreflight",
    "ControlledAction",
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
    "idempotency_digest",
    "resolved_context_digest",
    "resolved_resource_digest",
]
