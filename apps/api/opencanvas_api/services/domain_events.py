from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import JsonValue
from sqlalchemy import Select, and_, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    CanonicalGraphRelationship,
    Canvas,
    ControlledAgentExecution,
    DomainActivityEntry,
    DomainEventDeliveryAttempt,
    DomainEventOutbox,
    DomainEventProvenance,
    DomainEventRecord,
    Workspace,
    WorkspaceEventSequence,
    WorkspaceInvitation,
    WorkspaceMembership,
)

EVENT_REGISTRY_VERSION = "mobius-domain-events-v1"
EVENT_SCHEMA_VERSION = "domain-event-v1"
ACTIVITY_PROJECTION_VERSION = "activity-v1"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 30
MAX_EVENT_PAYLOAD_BYTES = 16_384
MAX_ACTIVITY_LIMIT = 100

DomainEventType = Literal[
    "graph.relationship.created",
    "graph.relationship.superseded",
    "graph.relationship.deactivated",
    "canonical.resource.created",
    "canonical.resource.updated",
    "canonical.resource.historical",
    "controlled.execution.started",
    "controlled.execution.completed",
    "controlled.execution.failed",
    "controlled.execution.canceled",
    "controlled.effect.committed",
    "controlled.rollback.committed",
    "evidence.bundle.requested",
    "evidence.bundle.generation_started",
    "evidence.bundle.completed",
    "evidence.bundle.failed",
    "evidence.bundle.accessed",
    "evidence.bundle.export_denied",
    "citation.rendering.completed",
    "citation.rendering.failed",
    "workflow.definition.created",
    "workflow.version.created",
    "workflow.version.validated",
    "workflow.version.activated",
    "workflow.version.disabled",
    "workflow.execution.requested",
    "workflow.execution.planned",
    "workflow.execution.started",
    "workflow.execution.awaiting_approval",
    "workflow.execution.completed",
    "workflow.execution.failed",
    "workflow.execution.canceled",
    "workflow.compensation.started",
    "workflow.compensation.completed",
    "workflow.compensation.failed",
    "workflow.step.started",
    "workflow.step.completed",
    "workflow.step.failed",
    "workflow.step.retry_scheduled",
    "workflow.step.awaiting_approval",
    "workflow.approval.requested",
    "workflow.approval.accepted",
    "workflow.approval.denied",
    "agent.identity.created",
    "agent.version.created",
    "agent.version.validated",
    "agent.version.validation_failed",
    "agent.version.activated",
    "agent.activation.requested",
    "agent.activation.approved",
    "agent.activation.denied",
    "agent.invocation.started",
    "agent.proposal.created",
    "agent.proposal.accepted",
    "agent.proposal.rejected",
    "agent.evaluation.recorded",
    "agent.communication.revision_proposed",
    "agent.communication.revision_accepted",
    "agent.communication.revision_rejected",
    "agent.suspended",
    "agent.retired",
    "invitation.created",
    "invitation.accepted",
    "invitation.declined",
    "invitation.expired",
    "invitation.revoked",
    "membership.activated",
    "membership.role_changed",
    "membership.suspended",
    "membership.restored",
    "membership.removed",
    "approval_authority.assigned",
    "approval_authority.replaced",
    "approval_authority.revoked",
]
SubjectKind = Literal[
    "canonical_resource",
    "graph_relationship",
    "controlled_execution",
    "controlled_effect",
    "controlled_rollback",
    "evidence_bundle",
    "citation",
    "workflow_definition",
    "workflow_version",
    "workflow_execution",
    "workflow_step",
    "agent_identity",
    "agent_version",
    "agent_activation",
    "agent_invocation",
    "agent_proposal",
    "agent_evaluation",
    "communication_revision",
    "workspace_invitation",
    "workspace_membership",
    "approval_authority_assignment",
]
OriginType = Literal[
    "authenticated_user",
    "canonical_service",
    "controlled_execution",
    "reserved_future_contract",
]
DeliveryState = Literal[
    "pending",
    "delivering",
    "retry_wait",
    "delivered",
    "terminal_failure",
]
SafeActivityStatus = Literal[
    "pending_delivery",
    "actively_delivering",
    "delivered",
    "retry_waiting",
    "terminal_delivery_failure",
]


@dataclass(frozen=True, slots=True)
class EventTypeSpec:
    subject_kind: SubjectKind
    allowed_payload_keys: frozenset[str]
    canvas_required: bool
    execution_required: bool = False
    reserved: bool = False


_GRAPH_PAYLOAD = frozenset({"relationshipType", "state", "reasonCode", "graphRevision"})
_CANONICAL_PAYLOAD = frozenset({"objectType", "version", "lifecycleState"})
_EXECUTION_PAYLOAD = frozenset({"status", "reasonCode"})
_EFFECT_PAYLOAD = frozenset({"action", "noteId", "resultingRevision"})
_BUNDLE_PAYLOAD = frozenset({"retrievalId", "bundleState", "artifactSha256", "failureCode"})
_CITATION_PAYLOAD = frozenset({"retrievalId", "style", "status", "failureCode"})
_WORKFLOW_VERSION_PAYLOAD = frozenset(
    {"workflowKind", "versionNumber", "lifecycleState", "reasonCode"}
)
_WORKFLOW_EXECUTION_PAYLOAD = frozenset(
    {"workflowDefinitionId", "workflowVersionId", "status", "outcome", "reasonCode"}
)
_WORKFLOW_STEP_PAYLOAD = frozenset(
    {
        "workflowExecutionId",
        "stepType",
        "status",
        "failureClass",
        "attemptNumber",
        "retryAt",
        "approvalStatus",
    }
)
_AGENT_PAYLOAD = frozenset(
    {
        "agentId",
        "agentVersionId",
        "agentKind",
        "versionNumber",
        "lifecycleState",
        "validationOutcome",
        "activationDecision",
        "workflowVersionId",
        "workflowExecutionId",
        "proposalKind",
        "evaluationOutcome",
        "preservationStatus",
        "decision",
        "reasonCode",
    }
)
_COLLABORATION_PAYLOAD = frozenset(
    {
        "state",
        "role",
        "reasonCode",
        "membershipId",
        "authorityGeneration",
        "previousState",
        "previousRole",
        "capability",
        "resourceKind",
        "maximumRiskClass",
    }
)

EVENT_TYPE_REGISTRY: dict[DomainEventType, EventTypeSpec] = {
    "graph.relationship.created": EventTypeSpec(
        "graph_relationship", _GRAPH_PAYLOAD, canvas_required=True
    ),
    "graph.relationship.superseded": EventTypeSpec(
        "graph_relationship", _GRAPH_PAYLOAD, canvas_required=True
    ),
    "graph.relationship.deactivated": EventTypeSpec(
        "graph_relationship", _GRAPH_PAYLOAD, canvas_required=True
    ),
    "canonical.resource.created": EventTypeSpec(
        "canonical_resource", _CANONICAL_PAYLOAD, canvas_required=False
    ),
    "canonical.resource.updated": EventTypeSpec(
        "canonical_resource", _CANONICAL_PAYLOAD, canvas_required=False
    ),
    "canonical.resource.historical": EventTypeSpec(
        "canonical_resource", _CANONICAL_PAYLOAD, canvas_required=False
    ),
    "controlled.execution.started": EventTypeSpec(
        "controlled_execution",
        _EXECUTION_PAYLOAD,
        canvas_required=True,
        execution_required=True,
    ),
    "controlled.execution.completed": EventTypeSpec(
        "controlled_execution",
        _EXECUTION_PAYLOAD,
        canvas_required=True,
        execution_required=True,
    ),
    "controlled.execution.failed": EventTypeSpec(
        "controlled_execution",
        _EXECUTION_PAYLOAD,
        canvas_required=True,
        execution_required=True,
    ),
    "controlled.execution.canceled": EventTypeSpec(
        "controlled_execution",
        _EXECUTION_PAYLOAD,
        canvas_required=True,
        execution_required=True,
    ),
    "controlled.effect.committed": EventTypeSpec(
        "controlled_effect",
        _EFFECT_PAYLOAD,
        canvas_required=True,
        execution_required=True,
    ),
    "controlled.rollback.committed": EventTypeSpec(
        "controlled_rollback",
        _EFFECT_PAYLOAD,
        canvas_required=True,
        execution_required=True,
    ),
    "evidence.bundle.requested": EventTypeSpec(
        "evidence_bundle", _BUNDLE_PAYLOAD, canvas_required=True
    ),
    "evidence.bundle.generation_started": EventTypeSpec(
        "evidence_bundle", _BUNDLE_PAYLOAD, canvas_required=True
    ),
    "evidence.bundle.completed": EventTypeSpec(
        "evidence_bundle", _BUNDLE_PAYLOAD, canvas_required=True
    ),
    "evidence.bundle.failed": EventTypeSpec(
        "evidence_bundle", _BUNDLE_PAYLOAD, canvas_required=True
    ),
    "evidence.bundle.accessed": EventTypeSpec(
        "evidence_bundle", _BUNDLE_PAYLOAD, canvas_required=True
    ),
    "evidence.bundle.export_denied": EventTypeSpec(
        "evidence_bundle", _BUNDLE_PAYLOAD, canvas_required=True
    ),
    "citation.rendering.completed": EventTypeSpec(
        "citation", _CITATION_PAYLOAD, canvas_required=True
    ),
    "citation.rendering.failed": EventTypeSpec("citation", _CITATION_PAYLOAD, canvas_required=True),
    "workflow.definition.created": EventTypeSpec(
        "workflow_definition", _WORKFLOW_VERSION_PAYLOAD, canvas_required=True
    ),
    "workflow.version.created": EventTypeSpec(
        "workflow_version", _WORKFLOW_VERSION_PAYLOAD, canvas_required=True
    ),
    "workflow.version.validated": EventTypeSpec(
        "workflow_version", _WORKFLOW_VERSION_PAYLOAD, canvas_required=True
    ),
    "workflow.version.activated": EventTypeSpec(
        "workflow_version", _WORKFLOW_VERSION_PAYLOAD, canvas_required=True
    ),
    "workflow.version.disabled": EventTypeSpec(
        "workflow_version", _WORKFLOW_VERSION_PAYLOAD, canvas_required=True
    ),
    "workflow.execution.requested": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.execution.planned": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.execution.started": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.execution.awaiting_approval": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.execution.completed": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.execution.failed": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.execution.canceled": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.compensation.started": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.compensation.completed": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.compensation.failed": EventTypeSpec(
        "workflow_execution", _WORKFLOW_EXECUTION_PAYLOAD, canvas_required=True
    ),
    "workflow.step.started": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "workflow.step.completed": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "workflow.step.failed": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "workflow.step.retry_scheduled": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "workflow.step.awaiting_approval": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "workflow.approval.requested": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "workflow.approval.accepted": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "workflow.approval.denied": EventTypeSpec(
        "workflow_step", _WORKFLOW_STEP_PAYLOAD, canvas_required=True
    ),
    "agent.identity.created": EventTypeSpec("agent_identity", _AGENT_PAYLOAD, canvas_required=True),
    "agent.version.created": EventTypeSpec("agent_version", _AGENT_PAYLOAD, canvas_required=True),
    "agent.version.validated": EventTypeSpec("agent_version", _AGENT_PAYLOAD, canvas_required=True),
    "agent.version.validation_failed": EventTypeSpec(
        "agent_version", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.version.activated": EventTypeSpec("agent_version", _AGENT_PAYLOAD, canvas_required=True),
    "agent.activation.requested": EventTypeSpec(
        "agent_activation", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.activation.approved": EventTypeSpec(
        "agent_activation", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.activation.denied": EventTypeSpec(
        "agent_activation", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.invocation.started": EventTypeSpec(
        "agent_invocation", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.proposal.created": EventTypeSpec("agent_proposal", _AGENT_PAYLOAD, canvas_required=True),
    "agent.proposal.accepted": EventTypeSpec(
        "agent_proposal", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.proposal.rejected": EventTypeSpec(
        "agent_proposal", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.evaluation.recorded": EventTypeSpec(
        "agent_evaluation", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.communication.revision_proposed": EventTypeSpec(
        "communication_revision", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.communication.revision_accepted": EventTypeSpec(
        "communication_revision", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.communication.revision_rejected": EventTypeSpec(
        "communication_revision", _AGENT_PAYLOAD, canvas_required=True
    ),
    "agent.suspended": EventTypeSpec("agent_identity", _AGENT_PAYLOAD, canvas_required=True),
    "agent.retired": EventTypeSpec("agent_identity", _AGENT_PAYLOAD, canvas_required=True),
    "invitation.created": EventTypeSpec(
        "workspace_invitation", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "invitation.accepted": EventTypeSpec(
        "workspace_invitation", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "invitation.declined": EventTypeSpec(
        "workspace_invitation", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "invitation.expired": EventTypeSpec(
        "workspace_invitation", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "invitation.revoked": EventTypeSpec(
        "workspace_invitation", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "membership.activated": EventTypeSpec(
        "workspace_membership", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "membership.role_changed": EventTypeSpec(
        "workspace_membership", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "membership.suspended": EventTypeSpec(
        "workspace_membership", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "membership.restored": EventTypeSpec(
        "workspace_membership", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "membership.removed": EventTypeSpec(
        "workspace_membership", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "approval_authority.assigned": EventTypeSpec(
        "approval_authority_assignment", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "approval_authority.replaced": EventTypeSpec(
        "approval_authority_assignment", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
    "approval_authority.revoked": EventTypeSpec(
        "approval_authority_assignment", _COLLABORATION_PAYLOAD, canvas_required=False
    ),
}


class DomainEventError(RuntimeError):
    code = "domain_event_error"
    safe_message = "The event operation could not be completed."


class DomainEventValidationError(DomainEventError):
    code = "domain_event_invalid"
    safe_message = "The event contract is invalid."


class DomainEventNotFoundError(DomainEventError):
    code = "domain_event_not_found"
    safe_message = "Event not found."


class DomainEventConflictError(DomainEventError):
    code = "domain_event_conflict"
    safe_message = "The event conflicts with existing state."


class DomainEventStorageError(DomainEventError):
    code = "domain_event_storage_failed"
    safe_message = "Event persistence is temporarily unavailable."


class OutboxOwnershipError(DomainEventConflictError):
    code = "outbox_ownership_invalid"
    safe_message = "The delivery claim is no longer valid."


@dataclass(frozen=True, slots=True)
class CreateDomainEvent:
    event_type: str
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID | None
    subject_id: uuid.UUID
    actor_user_id: uuid.UUID
    source_identity: str
    trace_id: uuid.UUID
    payload: dict[str, JsonValue]
    origin_type: OriginType
    related_id: uuid.UUID | None = None
    execution_id: uuid.UUID | None = None
    graph_revision: int | None = None
    audit_event_id: uuid.UUID | None = None
    graph_relationship_id: uuid.UUID | None = None
    graph_history_id: uuid.UUID | None = None
    effect_id: uuid.UUID | None = None
    rollback_result_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    max_attempts: int = DEFAULT_MAX_ATTEMPTS


@dataclass(frozen=True, slots=True)
class RecordedDomainEvent:
    event: DomainEventRecord
    provenance: DomainEventProvenance
    outbox: DomainEventOutbox
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    outbox_id: uuid.UUID
    event_id: uuid.UUID
    owner_id: str
    generation: int
    attempt_number: int
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityView:
    event: DomainEventRecord
    outbox: DomainEventOutbox
    status: SafeActivityStatus
    projected: bool


class DomainEventService:
    """Transactional event writer and bounded scoped reader.

    The caller owns commit/rollback. Event, provenance, and outbox rows are
    created in one savepoint and no post-commit reconstruction is used.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        after_event: Callable[[], Awaitable[None] | None] | None = None,
        after_provenance: Callable[[], Awaitable[None] | None] | None = None,
        after_outbox: Callable[[], Awaitable[None] | None] | None = None,
    ) -> None:
        self.session = session
        self.after_event = after_event
        self.after_provenance = after_provenance
        self.after_outbox = after_outbox

    async def record(self, command: CreateDomainEvent) -> RecordedDomainEvent:
        spec = _event_spec(command.event_type)
        if spec.reserved:
            raise DomainEventValidationError(
                "Reserved future event contracts cannot be emitted before their producer exists."
            )
        self._validate_command(command, spec)
        payload = _safe_payload(command.payload, spec.allowed_payload_keys)
        occurred_at = _aware_utc(command.occurred_at or datetime.now(UTC))
        scope_id = command.canvas_id or command.workspace_id
        request_payload: dict[str, object] = {
            "registryVersion": EVENT_REGISTRY_VERSION,
            "schemaVersion": EVENT_SCHEMA_VERSION,
            "eventType": command.event_type,
            "userId": str(command.user_id),
            "workspaceId": str(command.workspace_id),
            "canvasId": str(command.canvas_id) if command.canvas_id else None,
            "subjectKind": spec.subject_kind,
            "subjectId": str(command.subject_id),
            "relatedId": str(command.related_id) if command.related_id else None,
            "actorUserId": str(command.actor_user_id),
            "executionId": str(command.execution_id) if command.execution_id else None,
            "sourceIdentity": command.source_identity,
            "graphRevision": command.graph_revision,
            "payload": payload,
        }
        request_digest = _digest(request_payload)
        payload_digest = _digest(payload)
        existing = await self._existing(command, scope_id)
        if existing is not None:
            return self._replay(existing, request_digest)

        event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"mobius-domain-event:{request_digest}")
        provenance_id = uuid.uuid5(event_id, "provenance")
        outbox_id = uuid.uuid5(event_id, "outbox")
        try:
            async with self.session.begin_nested():
                await self._require_scope(command, spec)
                sequence = await self._next_sequence(command.workspace_id)
                event = DomainEventRecord(
                    event_id=event_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    canvas_id=command.canvas_id,
                    scope_id=scope_id,
                    sequence=sequence,
                    event_type=command.event_type,
                    registry_version=EVENT_REGISTRY_VERSION,
                    schema_version=EVENT_SCHEMA_VERSION,
                    subject_kind=spec.subject_kind,
                    subject_id=command.subject_id,
                    related_id=command.related_id,
                    actor_user_id=command.actor_user_id,
                    execution_id=command.execution_id,
                    source_identity=command.source_identity,
                    graph_revision=command.graph_revision,
                    occurred_at=occurred_at,
                    payload=payload,
                    payload_digest=payload_digest,
                    request_digest=request_digest,
                    trace_id=command.trace_id,
                    audit_event_id=command.audit_event_id,
                )
                self.session.add(event)
                await self.session.flush()
                await _run_hook(self.after_event)
                provenance_values = {
                    "eventId": str(event_id),
                    "actorUserId": str(command.actor_user_id),
                    "originType": command.origin_type,
                    "traceId": str(command.trace_id),
                    "executionId": str(command.execution_id) if command.execution_id else None,
                    "auditEventId": (
                        str(command.audit_event_id) if command.audit_event_id else None
                    ),
                    "graphRelationshipId": (
                        str(command.graph_relationship_id)
                        if command.graph_relationship_id
                        else None
                    ),
                    "graphHistoryId": (
                        str(command.graph_history_id) if command.graph_history_id else None
                    ),
                    "effectId": str(command.effect_id) if command.effect_id else None,
                    "rollbackResultId": (
                        str(command.rollback_result_id) if command.rollback_result_id else None
                    ),
                }
                provenance = DomainEventProvenance(
                    provenance_id=provenance_id,
                    event_id=event_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    actor_user_id=command.actor_user_id,
                    origin_type=command.origin_type,
                    trace_id=command.trace_id,
                    audit_event_id=command.audit_event_id,
                    execution_id=command.execution_id,
                    graph_relationship_id=command.graph_relationship_id,
                    graph_history_id=command.graph_history_id,
                    effect_id=command.effect_id,
                    rollback_result_id=command.rollback_result_id,
                    provenance_digest=_digest(provenance_values),
                )
                self.session.add(provenance)
                await self.session.flush()
                await _run_hook(self.after_provenance)
                outbox = DomainEventOutbox(
                    outbox_id=outbox_id,
                    event_id=event_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    delivery_state="pending",
                    eligible_at=occurred_at,
                    attempt_count=0,
                    max_attempts=command.max_attempts,
                    lease_generation=0,
                )
                self.session.add(outbox)
                await self.session.flush()
                await _run_hook(self.after_outbox)
        except IntegrityError as exc:
            existing = await self._existing(command, scope_id)
            if existing is not None:
                return self._replay(existing, request_digest)
            raise DomainEventConflictError("Event identity or sequence conflict.") from exc
        except SQLAlchemyError as exc:
            raise DomainEventStorageError("Event persistence failed.") from exc
        return RecordedDomainEvent(event=event, provenance=provenance, outbox=outbox)

    async def get_owned_event(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> RecordedDomainEvent:
        event = await self.session.scalar(
            select(DomainEventRecord).where(
                DomainEventRecord.event_id == event_id,
                DomainEventRecord.user_id == user_id,
                DomainEventRecord.workspace_id == workspace_id,
            )
        )
        if event is None:
            raise DomainEventNotFoundError()
        provenance = await self.session.scalar(
            select(DomainEventProvenance).where(
                DomainEventProvenance.event_id == event_id,
                DomainEventProvenance.user_id == user_id,
                DomainEventProvenance.workspace_id == workspace_id,
            )
        )
        outbox = await self.session.scalar(
            select(DomainEventOutbox).where(
                DomainEventOutbox.event_id == event_id,
                DomainEventOutbox.user_id == user_id,
                DomainEventOutbox.workspace_id == workspace_id,
            )
        )
        if provenance is None or outbox is None:
            raise DomainEventStorageError("Event evidence is incomplete.")
        return RecordedDomainEvent(event=event, provenance=provenance, outbox=outbox)

    async def list_activity(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID | None = None,
        subject_id: uuid.UUID | None = None,
        relationship_id: uuid.UUID | None = None,
        execution_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActivityView]:
        if not (1 <= limit <= MAX_ACTIVITY_LIMIT) or not (0 <= offset <= 100_000):
            raise DomainEventValidationError("Activity pagination is outside its bounds.")
        statement = (
            select(DomainEventRecord, DomainEventOutbox, DomainActivityEntry.activity_id)
            .join(DomainEventOutbox, DomainEventOutbox.event_id == DomainEventRecord.event_id)
            .outerjoin(
                DomainActivityEntry,
                DomainActivityEntry.event_id == DomainEventRecord.event_id,
            )
            .where(
                DomainEventRecord.user_id == user_id,
                DomainEventRecord.workspace_id == workspace_id,
            )
        )
        if canvas_id is not None:
            statement = statement.where(DomainEventRecord.canvas_id == canvas_id)
        if subject_id is not None:
            graph_endpoint = exists(
                select(CanonicalGraphRelationship.relationship_id).where(
                    CanonicalGraphRelationship.relationship_id == DomainEventRecord.subject_id,
                    or_(
                        CanonicalGraphRelationship.source_object_id == subject_id,
                        CanonicalGraphRelationship.target_object_id == subject_id,
                    ),
                )
            )
            statement = statement.where(
                or_(DomainEventRecord.subject_id == subject_id, graph_endpoint)
            )
        if relationship_id is not None:
            statement = statement.where(
                or_(
                    DomainEventRecord.subject_id == relationship_id,
                    DomainEventRecord.related_id == relationship_id,
                )
            )
        if execution_id is not None:
            statement = statement.where(DomainEventRecord.execution_id == execution_id)
        statement = statement.order_by(
            DomainEventRecord.sequence.desc(),
            DomainEventRecord.event_id.desc(),
        )
        rows = (await self.session.execute(statement.offset(offset).limit(limit))).all()
        return [
            ActivityView(
                event=row[0],
                outbox=row[1],
                status=_safe_activity_status(row[1].delivery_state),
                projected=row[2] is not None,
            )
            for row in rows
        ]

    async def _existing(
        self, command: CreateDomainEvent, scope_id: uuid.UUID
    ) -> RecordedDomainEvent | None:
        event = await self.session.scalar(
            select(DomainEventRecord).where(
                DomainEventRecord.user_id == command.user_id,
                DomainEventRecord.workspace_id == command.workspace_id,
                DomainEventRecord.scope_id == scope_id,
                DomainEventRecord.event_type == command.event_type,
                DomainEventRecord.source_identity == command.source_identity,
            )
        )
        if event is None:
            return None
        provenance = await self.session.scalar(
            select(DomainEventProvenance).where(DomainEventProvenance.event_id == event.event_id)
        )
        outbox = await self.session.scalar(
            select(DomainEventOutbox).where(DomainEventOutbox.event_id == event.event_id)
        )
        if provenance is None or outbox is None:
            raise DomainEventStorageError("Existing event evidence is incomplete.")
        return RecordedDomainEvent(event, provenance, outbox, duplicate=True)

    @staticmethod
    def _replay(existing: RecordedDomainEvent, request_digest: str) -> RecordedDomainEvent:
        if existing.event.request_digest != request_digest:
            raise DomainEventConflictError("Event idempotency identity was reused.")
        return RecordedDomainEvent(
            existing.event,
            existing.provenance,
            existing.outbox,
            duplicate=True,
        )

    async def _require_scope(self, command: CreateDomainEvent, spec: EventTypeSpec) -> None:
        workspace = await self.session.scalar(
            select(Workspace).where(
                Workspace.id == command.workspace_id,
                Workspace.owner_id == command.user_id,
            )
        )
        if workspace is None:
            raise DomainEventNotFoundError()
        if spec.subject_kind == "workspace_invitation":
            invitation = await self.session.scalar(
                select(WorkspaceInvitation).where(
                    WorkspaceInvitation.invitation_id == command.subject_id,
                    WorkspaceInvitation.workspace_id == command.workspace_id,
                )
            )
            accepted_membership_actor = await self.session.scalar(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.accepted_invitation_id == command.subject_id,
                    WorkspaceMembership.workspace_id == command.workspace_id,
                    WorkspaceMembership.user_id == command.actor_user_id,
                )
            )
            if invitation is None or (
                command.actor_user_id
                not in {
                    command.user_id,
                    invitation.recipient_user_id,
                    accepted_membership_actor,
                }
            ):
                raise DomainEventNotFoundError()
        elif spec.subject_kind == "workspace_membership":
            membership_actor = await self.session.scalar(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.membership_id == command.subject_id,
                    WorkspaceMembership.workspace_id == command.workspace_id,
                )
            )
            if membership_actor is None or command.actor_user_id not in {
                command.user_id,
                membership_actor,
            }:
                raise DomainEventNotFoundError()
        elif command.actor_user_id != command.user_id:
            raise DomainEventNotFoundError()
        if command.canvas_id is not None:
            canvas = await self.session.scalar(
                select(Canvas.id).where(
                    Canvas.id == command.canvas_id,
                    Canvas.workspace_id == command.workspace_id,
                )
            )
            if canvas is None:
                raise DomainEventNotFoundError()
        if command.execution_id is not None:
            execution = await self.session.scalar(
                select(ControlledAgentExecution.id).where(
                    ControlledAgentExecution.id == command.execution_id,
                    ControlledAgentExecution.user_id == command.user_id,
                    ControlledAgentExecution.workspace_id == command.workspace_id,
                )
            )
            if execution is None:
                raise DomainEventNotFoundError()

    async def _next_sequence(self, workspace_id: uuid.UUID) -> int:
        bind = self.session.get_bind()
        values = {"workspace_id": workspace_id, "last_sequence": 0}
        if bind.dialect.name == "postgresql":
            postgresql_seed = postgresql_insert(WorkspaceEventSequence).values(**values)
            await self.session.execute(
                postgresql_seed.on_conflict_do_nothing(index_elements=["workspace_id"])
            )
        elif bind.dialect.name == "sqlite":
            sqlite_seed = sqlite_insert(WorkspaceEventSequence).values(**values)
            await self.session.execute(
                sqlite_seed.on_conflict_do_nothing(index_elements=["workspace_id"])
            )
        else:
            if await self.session.get(WorkspaceEventSequence, workspace_id) is None:
                self.session.add(WorkspaceEventSequence(**values))
                await self.session.flush()
        sequence = await self.session.scalar(
            update(WorkspaceEventSequence)
            .where(WorkspaceEventSequence.workspace_id == workspace_id)
            .values(last_sequence=WorkspaceEventSequence.last_sequence + 1)
            .returning(WorkspaceEventSequence.last_sequence)
        )
        if sequence is None:
            raise DomainEventStorageError("Workspace event sequence is unavailable.")
        return sequence

    @staticmethod
    def _validate_command(command: CreateDomainEvent, spec: EventTypeSpec) -> None:
        if not command.source_identity.strip() or len(command.source_identity) > 128:
            raise DomainEventValidationError("Event source identity is invalid.")
        if spec.canvas_required and command.canvas_id is None:
            raise DomainEventValidationError("This event requires canvas scope.")
        if spec.execution_required and command.execution_id is None:
            raise DomainEventValidationError("This event requires controlled execution.")
        if command.graph_revision is not None and command.graph_revision <= 0:
            raise DomainEventValidationError("Graph revision must be positive.")
        if not 1 <= command.max_attempts <= 10:
            raise DomainEventValidationError("Outbox attempts are outside the supported bound.")
        if command.origin_type == "reserved_future_contract":
            raise DomainEventValidationError("Reserved future origins cannot be persisted.")


class DomainEventOutboxService:
    """Internal-only claim, fencing, retry, delivery, and projection boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_one(
        self,
        *,
        owner_id: str,
        now: datetime | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> OutboxClaim | None:
        if not owner_id.strip() or len(owner_id) > 128 or not 1 <= lease_seconds <= 300:
            raise DomainEventValidationError("Outbox claim parameters are invalid.")
        current = _aware_utc(now or datetime.now(UTC))
        eligible = and_(
            DomainEventOutbox.eligible_at <= current,
            DomainEventOutbox.attempt_count < DomainEventOutbox.max_attempts,
            or_(
                DomainEventOutbox.delivery_state.in_(("pending", "retry_wait")),
                and_(
                    DomainEventOutbox.delivery_state == "delivering",
                    DomainEventOutbox.lease_expires_at <= current,
                ),
            ),
        )
        statement: Select[tuple[DomainEventOutbox]] = (
            select(DomainEventOutbox)
            .where(eligible)
            .order_by(DomainEventOutbox.eligible_at, DomainEventOutbox.outbox_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        candidate = await self.session.scalar(statement)
        if candidate is None:
            return None
        generation = candidate.lease_generation + 1
        expires_at = current + timedelta(seconds=lease_seconds)
        try:
            claimed = await self.session.scalar(
                update(DomainEventOutbox)
                .where(
                    DomainEventOutbox.outbox_id == candidate.outbox_id,
                    DomainEventOutbox.lease_generation == candidate.lease_generation,
                    eligible,
                )
                .values(
                    delivery_state="delivering",
                    attempt_count=DomainEventOutbox.attempt_count + 1,
                    lease_owner_id=owner_id,
                    lease_generation=generation,
                    lease_acquired_at=current,
                    lease_expires_at=expires_at,
                    failure_classification=None,
                )
                .returning(DomainEventOutbox)
                .execution_options(synchronize_session=False)
            )
        except OperationalError as exc:
            if self.session.get_bind().dialect.name == "sqlite" and "locked" in str(exc).lower():
                return None
            raise DomainEventStorageError("Outbox claim failed.") from exc
        if claimed is None:
            return None
        await self.session.refresh(claimed)
        await self.session.flush()
        return OutboxClaim(
            outbox_id=claimed.outbox_id,
            event_id=claimed.event_id,
            owner_id=owner_id,
            generation=generation,
            attempt_number=claimed.attempt_count,
            lease_expires_at=expires_at,
        )

    async def complete(self, claim: OutboxClaim, *, now: datetime | None = None) -> None:
        current = _aware_utc(now or datetime.now(UTC))
        outbox = await self._owned_claim(claim, current)
        self.session.add(
            DomainEventDeliveryAttempt(
                attempt_id=uuid.uuid5(claim.event_id, f"attempt:{claim.generation}"),
                outbox_id=claim.outbox_id,
                event_id=claim.event_id,
                lease_generation=claim.generation,
                attempt_number=claim.attempt_number,
                outcome="delivered",
                failure_classification=None,
                recorded_at=current,
            )
        )
        outbox.delivery_state = "delivered"
        outbox.completed_at = current
        self._clear_lease(outbox)
        await self.session.flush()

    async def fail(
        self,
        claim: OutboxClaim,
        *,
        failure_classification: str,
        retryable: bool,
        now: datetime | None = None,
    ) -> DeliveryState:
        current = _aware_utc(now or datetime.now(UTC))
        outbox = await self._owned_claim(claim, current)
        safe_classification = _failure_classification(failure_classification)
        should_retry = retryable and outbox.attempt_count < outbox.max_attempts
        outcome: Literal["retry_scheduled", "terminal_failure"]
        if should_retry:
            outcome = "retry_scheduled"
            outbox.delivery_state = "retry_wait"
            outbox.eligible_at = current + _retry_delay(outbox.attempt_count)
        else:
            outcome = "terminal_failure"
            outbox.delivery_state = "terminal_failure"
            outbox.terminal_at = current
        outbox.failure_classification = safe_classification
        self._clear_lease(outbox)
        self.session.add(
            DomainEventDeliveryAttempt(
                attempt_id=uuid.uuid5(claim.event_id, f"attempt:{claim.generation}"),
                outbox_id=claim.outbox_id,
                event_id=claim.event_id,
                lease_generation=claim.generation,
                attempt_number=claim.attempt_number,
                outcome=outcome,
                failure_classification=safe_classification,
                recorded_at=current,
            )
        )
        await self.session.flush()
        return cast(DeliveryState, outbox.delivery_state)

    async def project_activity(self, claim: OutboxClaim) -> bool:
        event = await self.session.get(DomainEventRecord, claim.event_id)
        if (
            event is None
            or event.registry_version != EVENT_REGISTRY_VERSION
            or event.schema_version != EVENT_SCHEMA_VERSION
        ):
            raise DomainEventValidationError("Event schema is unsupported.")
        existing = await self.session.scalar(
            select(DomainActivityEntry).where(DomainActivityEntry.event_id == event.event_id)
        )
        if existing is not None:
            if (
                existing.user_id != event.user_id
                or existing.workspace_id != event.workspace_id
                or existing.sequence != event.sequence
                or existing.event_type != event.event_type
                or existing.subject_id != event.subject_id
            ):
                raise DomainEventConflictError("Activity projection conflicts with its event.")
            return False
        self.session.add(
            DomainActivityEntry(
                activity_id=uuid.uuid5(event.event_id, ACTIVITY_PROJECTION_VERSION),
                event_id=event.event_id,
                user_id=event.user_id,
                workspace_id=event.workspace_id,
                canvas_id=event.canvas_id,
                sequence=event.sequence,
                event_type=event.event_type,
                subject_kind=event.subject_kind,
                subject_id=event.subject_id,
                actor_user_id=event.actor_user_id,
                trace_id=event.trace_id,
                projection_version=ACTIVITY_PROJECTION_VERSION,
                occurred_at=event.occurred_at,
            )
        )
        await self.session.flush()
        return True

    async def process_one(
        self,
        *,
        owner_id: str,
        now: datetime | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> OutboxClaim | None:
        current = _aware_utc(now or datetime.now(UTC))
        async with self.session.begin_nested():
            claim = await self.claim_one(
                owner_id=owner_id,
                now=current,
                lease_seconds=lease_seconds,
            )
            if claim is None:
                return None
            await self.project_activity(claim)
            await self.complete(claim, now=current)
        return claim

    async def _owned_claim(self, claim: OutboxClaim, current: datetime) -> DomainEventOutbox:
        outbox = await self.session.get(DomainEventOutbox, claim.outbox_id)
        if (
            outbox is None
            or outbox.event_id != claim.event_id
            or outbox.delivery_state != "delivering"
            or outbox.lease_owner_id != claim.owner_id
            or outbox.lease_generation != claim.generation
            or outbox.lease_expires_at is None
            or _aware_utc(outbox.lease_expires_at) <= current
        ):
            raise OutboxOwnershipError()
        return outbox

    @staticmethod
    def _clear_lease(outbox: DomainEventOutbox) -> None:
        outbox.lease_owner_id = None
        outbox.lease_acquired_at = None
        outbox.lease_expires_at = None


def _event_spec(event_type: str) -> EventTypeSpec:
    try:
        return EVENT_TYPE_REGISTRY[cast(DomainEventType, event_type)]
    except KeyError as exc:
        raise DomainEventValidationError("Unknown domain event type.") from exc


def _safe_payload(payload: dict[str, JsonValue], allowed_keys: frozenset[str]) -> dict[str, object]:
    unexpected = set(payload) - allowed_keys
    if unexpected:
        raise DomainEventValidationError("Event payload contains unsupported fields.")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_EVENT_PAYLOAD_BYTES:
        raise DomainEventValidationError("Event payload is too large.")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise DomainEventValidationError("Event payload must be an object.")
    return cast(dict[str, object], decoded)


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _safe_activity_status(state: str) -> SafeActivityStatus:
    mapping: dict[str, SafeActivityStatus] = {
        "pending": "pending_delivery",
        "delivering": "actively_delivering",
        "delivered": "delivered",
        "retry_wait": "retry_waiting",
        "terminal_failure": "terminal_delivery_failure",
    }
    try:
        return mapping[state]
    except KeyError as exc:
        raise DomainEventStorageError("Outbox state is inconsistent.") from exc


def _failure_classification(value: str) -> str:
    allowed = {
        "consumer_retryable",
        "consumer_rejected",
        "unsupported_schema",
        "scope_mismatch",
        "projection_conflict",
    }
    return value if value in allowed else "unsafe_failure"


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** max(0, attempt_count - 1)))


async def _run_hook(hook: Callable[[], Awaitable[None] | None] | None) -> None:
    if hook is None:
        return
    result = hook()
    if result is not None:
        await result


__all__ = [
    "ACTIVITY_PROJECTION_VERSION",
    "EVENT_REGISTRY_VERSION",
    "EVENT_SCHEMA_VERSION",
    "EVENT_TYPE_REGISTRY",
    "ActivityView",
    "CreateDomainEvent",
    "DomainEventConflictError",
    "DomainEventError",
    "DomainEventNotFoundError",
    "DomainEventOutboxService",
    "DomainEventService",
    "DomainEventStorageError",
    "DomainEventValidationError",
    "OutboxClaim",
    "OutboxOwnershipError",
    "RecordedDomainEvent",
]
