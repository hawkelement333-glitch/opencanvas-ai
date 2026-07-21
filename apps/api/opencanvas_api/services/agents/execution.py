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

from opencanvas_api.db.models import Canvas, ControlledAgentRequestIdentity, Workspace
from opencanvas_api.services.agents.contracts import (
    SCHEMA_VERSION,
    AuditAttribute,
    AuditEvent,
    Capability,
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
    "RequestReservation",
    "idempotency_digest",
]
