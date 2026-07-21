from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    CanonicalChunk,
    CanonicalDocument,
    CanonicalExecution,
    CanonicalNote,
    CanonicalRelationship,
    TraceEvent,
    Workspace,
)
from opencanvas_api.services.canonical.events import (
    CanonicalObjectCreated,
    CanonicalObjectDeleted,
    CanonicalObjectTransitioned,
    CanonicalObjectUpdated,
    CanonicalRelationshipCreated,
    CanonicalRelationshipRemoved,
    DomainEvent,
    DomainEventPublisher,
    ExecutionCompleted,
    ExecutionFailed,
    ExecutionStarted,
    InMemoryDomainEventBus,
    TraceEventRecorded,
    WorkspaceCreated,
    WorkspaceDeleted,
    WorkspaceTransitioned,
    WorkspaceUpdated,
)
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalDomainError,
    CanonicalStorageError,
    CanonicalValidationError,
    LifecycleState,
)
from opencanvas_api.services.canonical.repository import (
    CanonicalAggregate,
    CanonicalRepository,
)
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    FailTraceInput,
    StartTraceInput,
    TraceContext,
    TraceErrorInfo,
    TracePersistenceError,
    TraceService,
)

CanonicalObjectType = Literal["document", "chunk", "note", "execution", "relationship"]
RelationshipType = Literal[
    "contains",
    "part_of",
    "references",
    "derived_from",
    "related_to",
]
DocumentProcessingStatus = Literal["created", "processing", "ready", "failed"]
ExecutionStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
type JsonObject = dict[str, JsonValue]
CANONICAL_OBJECT_TYPES = frozenset({"document", "chunk", "note", "execution", "relationship"})
RELATIONSHIP_TYPES = frozenset({"contains", "part_of", "references", "derived_from", "related_to"})
DOCUMENT_PROCESSING_STATUSES = frozenset({"created", "processing", "ready", "failed"})
EXECUTION_STATUSES = frozenset({"pending", "running", "succeeded", "failed", "cancelled"})


class CanonicalInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MutationContext(CanonicalInputModel):
    actor_id: str | None = Field(default=None, min_length=1, max_length=255)
    parent_trace_id: uuid.UUID | None = None

    @field_validator("actor_id")
    @classmethod
    def trim_actor_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (trimmed := value.strip()):
            raise ValueError("actor_id must not be blank")
        return trimmed


class CreateWorkspaceInput(MutationContext):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=20_000)
    owner_id: uuid.UUID | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not (trimmed := value.strip()):
            raise ValueError("workspace name must not be blank")
        return trimmed


class UpdateWorkspaceInput(MutationContext):
    workspace_id: uuid.UUID
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=20_000)
    owner_id: uuid.UUID | None = None
    metadata: JsonObject | None = None

    @field_validator("name")
    @classmethod
    def trim_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (trimmed := value.strip()):
            raise ValueError("workspace name must not be blank")
        return trimmed

    @model_validator(mode="after")
    def contains_change(self) -> UpdateWorkspaceInput:
        if not self.model_fields_set.intersection({"name", "description", "owner_id", "metadata"}):
            raise ValueError("at least one workspace field must be supplied")
        return self


class TransitionWorkspaceInput(MutationContext):
    workspace_id: uuid.UUID
    expected_version: int = Field(ge=1)
    target_state: LifecycleState


class CreateObjectInput(MutationContext):
    workspace_id: uuid.UUID
    object_type: CanonicalObjectType
    payload: JsonObject
    metadata: JsonObject = Field(default_factory=dict)


class UpdateObjectInput(MutationContext):
    workspace_id: uuid.UUID
    object_id: uuid.UUID
    expected_version: int = Field(ge=1)
    payload: JsonObject | None = None
    metadata: JsonObject | None = None

    @model_validator(mode="after")
    def contains_change(self) -> UpdateObjectInput:
        if self.payload is None and self.metadata is None:
            raise ValueError("payload or metadata must be supplied")
        if self.payload == {}:
            raise ValueError("payload must contain at least one field")
        return self


class TransitionObjectInput(MutationContext):
    workspace_id: uuid.UUID
    object_id: uuid.UUID
    expected_version: int = Field(ge=1)
    target_state: LifecycleState


class CreateRelationshipInput(MutationContext):
    workspace_id: uuid.UUID
    relationship_type: RelationshipType
    source_object_id: uuid.UUID
    target_object_id: uuid.UUID
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def rejects_self_relation(self) -> CreateRelationshipInput:
        if self.source_object_id == self.target_object_id:
            raise ValueError("a canonical relationship cannot reference itself")
        return self


class RemoveRelationshipInput(MutationContext):
    workspace_id: uuid.UUID
    relationship_id: uuid.UUID
    expected_version: int = Field(ge=1)


class ObjectQueryFilters(CanonicalInputModel):
    object_type: CanonicalObjectType | None = None
    lifecycle_state: LifecycleState | None = None
    include_deleted: bool = False
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=100_000)


class WorkspaceQueryFilters(CanonicalInputModel):
    owner_id: uuid.UUID | None = None
    lifecycle_state: LifecycleState | None = None
    include_deleted: bool = False
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=100_000)


class RelationshipQueryFilters(CanonicalInputModel):
    relationship_type: RelationshipType | None = None
    source_object_id: uuid.UUID | None = None
    target_object_id: uuid.UUID | None = None
    include_deleted: bool = False
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=100_000)


class DocumentPayload(CanonicalInputModel):
    display_name: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=64)
    processing_status: DocumentProcessingStatus = "created"
    source_metadata: JsonObject = Field(default_factory=dict)
    legacy_document_id: uuid.UUID | None = None

    @field_validator("display_name", "source_type")
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not (trimmed := value.strip()):
            raise ValueError("document text must not be blank")
        return trimmed


class DocumentPatch(CanonicalInputModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    processing_status: DocumentProcessingStatus | None = None
    source_metadata: JsonObject | None = None


class ChunkPayload(CanonicalInputModel):
    document_object_id: uuid.UUID
    ordered_position: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=1_000_000)
    source_location: JsonObject = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk content must not be blank")
        return value


class ChunkPatch(CanonicalInputModel):
    ordered_position: int | None = Field(default=None, ge=0)
    content: str | None = Field(default=None, min_length=1, max_length=1_000_000)
    source_location: JsonObject | None = None

    @field_validator("content")
    @classmethod
    def reject_optional_blank_content(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("chunk content must not be blank")
        return value


class NotePayload(CanonicalInputModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", max_length=1_000_000)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        if not (trimmed := value.strip()):
            raise ValueError("note title must not be blank")
        return trimmed


class NotePatch(CanonicalInputModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=1_000_000)


class ExecutionPayload(CanonicalInputModel):
    execution_type: str = Field(min_length=1, max_length=64)
    status: ExecutionStatus = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    trace_id: uuid.UUID | None = None
    inputs_metadata: JsonObject = Field(default_factory=dict)
    outputs_metadata: JsonObject = Field(default_factory=dict)
    failure: JsonObject | None = None

    @field_validator("execution_type")
    @classmethod
    def trim_execution_type(cls, value: str) -> str:
        if not (trimmed := value.strip()):
            raise ValueError("execution type must not be blank")
        return trimmed

    @model_validator(mode="after")
    def fields_are_coherent(self) -> ExecutionPayload:
        _validate_execution(self.status, self.started_at, self.completed_at, self.failure)
        return self


class ExecutionPatch(CanonicalInputModel):
    execution_type: str | None = Field(default=None, min_length=1, max_length=64)
    status: ExecutionStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    trace_id: uuid.UUID | None = None
    inputs_metadata: JsonObject | None = None
    outputs_metadata: JsonObject | None = None
    failure: JsonObject | None = None


type PayloadModel = DocumentPayload | ChunkPayload | NotePayload | ExecutionPayload
MutationT = TypeVar("MutationT")
Mutation = Callable[[TraceContext], Awaitable[tuple[MutationT, list[DomainEvent]]]]


class CanonicalService:
    """Canonical mutation boundary that flushes but never commits.

    Successful callers commit the mutation and success Trace atomically. When a mutation raises a
    CanonicalDomainError, its savepoint has already rolled back domain rows; the caller must commit
    the remaining started/failed Trace evidence before translating or re-raising the error.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: CanonicalRepository | None = None,
        trace_service: TraceService | None = None,
        event_bus: DomainEventPublisher | None = None,
    ) -> None:
        self._session = session
        self.repository = repository or CanonicalRepository(session)
        self.trace_service = trace_service or TraceService(session)
        self.event_bus = event_bus or InMemoryDomainEventBus()

    async def create_workspace(self, input_data: CreateWorkspaceInput) -> Workspace:
        workspace_id = uuid.uuid4()

        async def mutation(context: TraceContext) -> tuple[Workspace, list[DomainEvent]]:
            workspace = await self.repository.create_workspace(
                workspace_id=workspace_id,
                name=input_data.name,
                description=input_data.description,
                owner_id=input_data.owner_id,
                lifecycle_state=LifecycleState.CREATED,
                metadata_payload=_json_object(input_data.metadata),
            )
            return workspace, [
                WorkspaceCreated(
                    workspace_id=workspace.id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=workspace.id,
                    object_type="workspace",
                    object_version=workspace.version,
                    metadata=input_data.metadata,
                )
            ]

        return await self._run_traced(
            workspace_id=workspace_id,
            object_id=workspace_id,
            object_type="workspace",
            operation="canonical.workspace.create",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def update_workspace(self, input_data: UpdateWorkspaceInput) -> Workspace:
        async def mutation(context: TraceContext) -> tuple[Workspace, list[DomainEvent]]:
            current = await self.repository.get_workspace(input_data.workspace_id)
            if current.lifecycle_state == LifecycleState.ARCHIVED.value:
                raise CanonicalConflictError(
                    "Archived workspaces must be reactivated before they can be updated."
                )
            fields = input_data.model_fields_set
            name = current.name
            if "name" in fields:
                if input_data.name is None:
                    raise CanonicalValidationError("Workspace name cannot be null.")
                name = input_data.name
            workspace = await self.repository.update_workspace(
                workspace_id=input_data.workspace_id,
                expected_version=input_data.expected_version,
                name=name,
                description=(
                    input_data.description if "description" in fields else current.description
                ),
                owner_id=input_data.owner_id if "owner_id" in fields else current.owner_id,
                metadata_payload=(
                    _json_object(input_data.metadata or {})
                    if "metadata" in fields
                    else current.metadata_payload
                ),
            )
            return workspace, [
                WorkspaceUpdated(
                    workspace_id=workspace.id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=workspace.id,
                    object_type="workspace",
                    object_version=workspace.version,
                )
            ]

        return await self._run_traced(
            workspace_id=input_data.workspace_id,
            object_id=input_data.workspace_id,
            object_type="workspace",
            operation="canonical.workspace.update",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def transition_workspace(self, input_data: TransitionWorkspaceInput) -> Workspace:
        previous_state = ""

        async def mutation(context: TraceContext) -> tuple[Workspace, list[DomainEvent]]:
            nonlocal previous_state
            current = await self.repository.get_workspace(
                input_data.workspace_id, include_deleted=True
            )
            previous_state = current.lifecycle_state
            workspace = await self.repository.transition_workspace(
                workspace_id=input_data.workspace_id,
                expected_version=input_data.expected_version,
                target_state=input_data.target_state,
            )
            event: DomainEvent
            if input_data.target_state is LifecycleState.DELETED:
                event = WorkspaceDeleted(
                    workspace_id=workspace.id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=workspace.id,
                    object_type="workspace",
                    object_version=workspace.version,
                    previous_state=previous_state,
                )
            else:
                event = WorkspaceTransitioned(
                    workspace_id=workspace.id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=workspace.id,
                    object_type="workspace",
                    object_version=workspace.version,
                    previous_state=previous_state,
                    current_state=workspace.lifecycle_state,
                )
            return workspace, [event]

        return await self._run_traced(
            workspace_id=input_data.workspace_id,
            object_id=input_data.workspace_id,
            object_type="workspace",
            operation="canonical.workspace.transition",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def create_object(self, input_data: CreateObjectInput) -> CanonicalAggregate:
        object_id = uuid.uuid4()

        async def mutation(context: TraceContext) -> tuple[CanonicalAggregate, list[DomainEvent]]:
            if input_data.object_type == "relationship":
                raise CanonicalValidationError(
                    "Create relationship objects through create_relationship()."
                )
            workspace = await self.repository.get_workspace(input_data.workspace_id)
            if workspace.lifecycle_state == LifecycleState.ARCHIVED.value:
                raise CanonicalConflictError(
                    "Archived workspaces must be reactivated before objects can be created."
                )
            payload = _parse_create_payload(input_data.object_type, input_data.payload)
            if isinstance(payload, DocumentPayload) and payload.legacy_document_id is not None:
                await self.repository.validate_legacy_document(
                    input_data.workspace_id, payload.legacy_document_id
                )
            if isinstance(payload, ChunkPayload):
                parent = await self.repository.get_object(
                    input_data.workspace_id, payload.document_object_id
                )
                if parent.object.object_type != "document":
                    raise CanonicalValidationError(
                        "document_object_id must reference a document in the same workspace."
                    )
            detail = _new_detail(object_id, payload, context.trace_id)
            aggregate = await self.repository.create_object(
                object_id=object_id,
                workspace_id=input_data.workspace_id,
                object_type=input_data.object_type,
                lifecycle_state=LifecycleState.CREATED,
                metadata_payload=_json_object(input_data.metadata),
                detail=detail,
            )
            events: list[DomainEvent] = [
                CanonicalObjectCreated(
                    workspace_id=input_data.workspace_id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=object_id,
                    object_type=input_data.object_type,
                    object_version=1,
                )
            ]
            events.extend(
                _execution_events(aggregate, previous_status=None, actor=input_data.actor_id)
            )
            return aggregate, events

        return await self._run_traced(
            workspace_id=input_data.workspace_id,
            object_id=object_id,
            object_type=input_data.object_type,
            operation="canonical.object.create",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def update_object(self, input_data: UpdateObjectInput) -> CanonicalAggregate:
        async def mutation(context: TraceContext) -> tuple[CanonicalAggregate, list[DomainEvent]]:
            current = await self.repository.get_object(
                input_data.workspace_id, input_data.object_id
            )
            if current.object.object_type == "relationship":
                raise CanonicalValidationError("Relationship objects have dedicated mutations.")
            if current.object.lifecycle_state == LifecycleState.ARCHIVED.value:
                raise CanonicalConflictError(
                    "Archived objects must be reactivated before they can be updated."
                )
            previous_status = (
                current.detail.status if isinstance(current.detail, CanonicalExecution) else None
            )
            parsed_payload = None
            if input_data.payload is not None:
                parsed_payload = _merge_and_validate_payload(current, input_data.payload)
            aggregate = await self.repository.update_object_metadata(
                workspace_id=input_data.workspace_id,
                object_id=input_data.object_id,
                expected_version=input_data.expected_version,
                metadata_payload=(
                    _json_object(input_data.metadata)
                    if input_data.metadata is not None
                    else current.object.metadata_payload
                ),
            )
            if parsed_payload is not None:
                _apply_payload(aggregate, parsed_payload)
                await self.repository.flush()
            events: list[DomainEvent] = [
                CanonicalObjectUpdated(
                    workspace_id=input_data.workspace_id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=input_data.object_id,
                    object_type=aggregate.object.object_type,
                    object_version=aggregate.object.version,
                )
            ]
            events.extend(
                _execution_events(
                    aggregate,
                    previous_status=previous_status,
                    actor=input_data.actor_id,
                )
            )
            return aggregate, events

        return await self._run_traced(
            workspace_id=input_data.workspace_id,
            object_id=input_data.object_id,
            object_type="canonical_object",
            operation="canonical.object.update",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def transition_object(self, input_data: TransitionObjectInput) -> CanonicalAggregate:
        async def mutation(context: TraceContext) -> tuple[CanonicalAggregate, list[DomainEvent]]:
            await self.repository.get_workspace(input_data.workspace_id)
            current = await self.repository.get_object(
                input_data.workspace_id, input_data.object_id, include_deleted=True
            )
            if current.object.object_type == "relationship":
                raise CanonicalValidationError(
                    "Remove relationship objects through remove_relationship()."
                )
            if input_data.target_state is LifecycleState.DELETED:
                if (
                    current.object.object_type == "document"
                    and await self.repository.has_live_chunk_children(
                        input_data.workspace_id, input_data.object_id
                    )
                ):
                    raise CanonicalConflictError(
                        "Delete or reassign live chunks before deleting this document."
                    )
                outgoing = await self.repository.list_relationships(
                    input_data.workspace_id,
                    source_object_id=input_data.object_id,
                    limit=1,
                )
                incoming = await self.repository.list_relationships(
                    input_data.workspace_id,
                    target_object_id=input_data.object_id,
                    limit=1,
                )
                if outgoing or incoming:
                    raise CanonicalConflictError(
                        "Remove active relationships before deleting this object."
                    )
            previous_state = current.object.lifecycle_state
            aggregate = await self.repository.transition_object(
                workspace_id=input_data.workspace_id,
                object_id=input_data.object_id,
                expected_version=input_data.expected_version,
                target_state=input_data.target_state,
            )
            if input_data.target_state is LifecycleState.DELETED:
                event: DomainEvent = CanonicalObjectDeleted(
                    workspace_id=input_data.workspace_id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=input_data.object_id,
                    object_type=aggregate.object.object_type,
                    object_version=aggregate.object.version,
                    previous_state=previous_state,
                )
            else:
                event = CanonicalObjectTransitioned(
                    workspace_id=input_data.workspace_id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=input_data.object_id,
                    object_type=aggregate.object.object_type,
                    object_version=aggregate.object.version,
                    previous_state=previous_state,
                    current_state=aggregate.object.lifecycle_state,
                )
            return aggregate, [event]

        return await self._run_traced(
            workspace_id=input_data.workspace_id,
            object_id=input_data.object_id,
            object_type="canonical_object",
            operation="canonical.object.transition",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def create_relationship(self, input_data: CreateRelationshipInput) -> CanonicalAggregate:
        relationship_id = uuid.uuid4()

        async def mutation(context: TraceContext) -> tuple[CanonicalAggregate, list[DomainEvent]]:
            workspace = await self.repository.get_workspace(input_data.workspace_id)
            if workspace.lifecycle_state == LifecycleState.ARCHIVED.value:
                raise CanonicalConflictError(
                    "Archived workspaces must be reactivated before relationships can be created."
                )
            await self.repository.get_object(input_data.workspace_id, input_data.source_object_id)
            await self.repository.get_object(input_data.workspace_id, input_data.target_object_id)
            existing = await self.repository.list_relationships(
                input_data.workspace_id,
                relationship_type=input_data.relationship_type,
                source_object_id=input_data.source_object_id,
                target_object_id=input_data.target_object_id,
                include_deleted=True,
                limit=1,
            )
            if existing:
                raise CanonicalConflictError("Canonical relationship already exists.")
            detail = CanonicalRelationship(
                object_id=relationship_id,
                workspace_id=input_data.workspace_id,
                source_object_id=input_data.source_object_id,
                target_object_id=input_data.target_object_id,
                relationship_type=input_data.relationship_type,
                created_by=_actor_uuid(input_data.actor_id),
                trace_id=context.trace_id,
            )
            aggregate = await self.repository.create_object(
                object_id=relationship_id,
                workspace_id=input_data.workspace_id,
                object_type="relationship",
                lifecycle_state=LifecycleState.CREATED,
                metadata_payload=_json_object(input_data.metadata),
                detail=detail,
            )
            return aggregate, [
                CanonicalRelationshipCreated(
                    workspace_id=input_data.workspace_id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=relationship_id,
                    object_type="relationship",
                    object_version=1,
                    relationship_id=relationship_id,
                    relationship_type=input_data.relationship_type,
                    source_object_id=input_data.source_object_id,
                    target_object_id=input_data.target_object_id,
                )
            ]

        return await self._run_traced(
            workspace_id=input_data.workspace_id,
            object_id=relationship_id,
            object_type="relationship",
            operation="canonical.relationship.create",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def remove_relationship(self, input_data: RemoveRelationshipInput) -> CanonicalAggregate:
        async def mutation(context: TraceContext) -> tuple[CanonicalAggregate, list[DomainEvent]]:
            await self.repository.get_workspace(input_data.workspace_id)
            current = await self.repository.get_object(
                input_data.workspace_id,
                input_data.relationship_id,
                include_deleted=True,
            )
            if not isinstance(current.detail, CanonicalRelationship):
                raise CanonicalValidationError("The requested object is not a relationship.")
            aggregate = await self.repository.transition_object(
                workspace_id=input_data.workspace_id,
                object_id=input_data.relationship_id,
                expected_version=input_data.expected_version,
                target_state=LifecycleState.DELETED,
            )
            detail = cast(CanonicalRelationship, aggregate.detail)
            return aggregate, [
                CanonicalRelationshipRemoved(
                    workspace_id=input_data.workspace_id,
                    actor_id=input_data.actor_id,
                    trace_id=context.trace_id,
                    object_id=input_data.relationship_id,
                    object_type="relationship",
                    object_version=aggregate.object.version,
                    relationship_id=input_data.relationship_id,
                    relationship_type=detail.relationship_type,
                    source_object_id=detail.source_object_id,
                    target_object_id=detail.target_object_id,
                )
            ]

        return await self._run_traced(
            workspace_id=input_data.workspace_id,
            object_id=input_data.relationship_id,
            object_type="relationship",
            operation="canonical.relationship.remove",
            actor_id=input_data.actor_id,
            parent_trace_id=input_data.parent_trace_id,
            mutation=mutation,
        )

    async def get_workspace(
        self, workspace_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Workspace:
        return await self.repository.get_workspace(workspace_id, include_deleted=include_deleted)

    async def get_object(
        self,
        workspace_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> CanonicalAggregate:
        return await self.repository.get_object(
            workspace_id, object_id, include_deleted=include_deleted
        )

    async def list_workspaces(
        self, filters: WorkspaceQueryFilters | None = None
    ) -> list[Workspace]:
        query = filters or WorkspaceQueryFilters()
        return await self.repository.list_workspaces(
            owner_id=query.owner_id,
            lifecycle_state=query.lifecycle_state,
            include_deleted=query.include_deleted,
            limit=query.limit,
            offset=query.offset,
        )

    async def list_objects(
        self, workspace_id: uuid.UUID, filters: ObjectQueryFilters | None = None
    ) -> list[CanonicalAggregate]:
        query = filters or ObjectQueryFilters()
        return await self.repository.list_objects(
            workspace_id,
            object_type=query.object_type,
            lifecycle_state=query.lifecycle_state,
            include_deleted=query.include_deleted,
            limit=query.limit,
            offset=query.offset,
        )

    async def list_relationships(
        self, workspace_id: uuid.UUID, filters: RelationshipQueryFilters | None = None
    ) -> list[CanonicalAggregate]:
        query = filters or RelationshipQueryFilters()
        return await self.repository.list_relationships(
            workspace_id,
            relationship_type=query.relationship_type,
            source_object_id=query.source_object_id,
            target_object_id=query.target_object_id,
            include_deleted=query.include_deleted,
            limit=query.limit,
            offset=query.offset,
        )

    async def _run_traced(
        self,
        *,
        workspace_id: uuid.UUID,
        object_id: uuid.UUID,
        object_type: str,
        operation: str,
        actor_id: str | None,
        parent_trace_id: uuid.UUID | None,
        mutation: Mutation[MutationT],
    ) -> MutationT:
        trace_workspace_id = workspace_id
        trace_user_id = _actor_user_id(actor_id)
        try:
            context = await self.trace_service.start_trace(
                StartTraceInput(
                    parent_trace_id=parent_trace_id,
                    event_type=f"{operation}.started",
                    actor_id=actor_id,
                    actor_type="user" if actor_id is not None else "system",
                    user_id=trace_user_id,
                    workspace_id=trace_workspace_id,
                    object_id=object_id,
                    object_type=object_type,
                    operation=operation,
                    metadata={"objectVersion": None},
                )
            )
        except TracePersistenceError as exc:
            raise CanonicalStorageError("Canonical trace persistence failed.") from exc
        await self._publish_trace_marker(context.start_event, actor_id)

        try:
            async with self._session.begin_nested():
                result, events = await mutation(context)
                success_object_type = next(
                    (event.object_type for event in events if event.object_type is not None),
                    object_type,
                )
                completed = await self.trace_service.complete_trace(
                    CompleteTraceInput(
                        trace_id=context.trace_id,
                        parent_trace_id=context.parent_trace_id,
                        event_type=f"{operation}.succeeded",
                        actor_id=actor_id,
                        actor_type="user" if actor_id is not None else "system",
                        user_id=trace_user_id,
                        workspace_id=workspace_id,
                        object_id=object_id,
                        object_type=success_object_type,
                        operation=operation,
                        metadata=_success_trace_metadata(events),
                    )
                )
        except CanonicalDomainError as exc:
            await self._record_failure(
                context=context,
                workspace_id=trace_workspace_id,
                object_id=object_id,
                object_type=object_type,
                operation=operation,
                actor_id=actor_id,
                error=exc,
            )
            raise
        except TracePersistenceError as exc:
            error = CanonicalStorageError("Canonical trace completion failed.")
            await self._record_failure(
                context=context,
                workspace_id=trace_workspace_id,
                object_id=object_id,
                object_type=object_type,
                operation=operation,
                actor_id=actor_id,
                error=error,
            )
            raise error from exc
        except Exception as exc:
            error = CanonicalStorageError("Canonical mutation failed.")
            await self._record_failure(
                context=context,
                workspace_id=trace_workspace_id,
                object_id=object_id,
                object_type=object_type,
                operation=operation,
                actor_id=actor_id,
                error=error,
            )
            raise error from exc

        await self._publish_trace_marker(completed, actor_id)
        for event in events:
            await self.event_bus.publish(event)
        return result

    async def _record_failure(
        self,
        *,
        context: TraceContext,
        workspace_id: uuid.UUID | None,
        object_id: uuid.UUID,
        object_type: str,
        operation: str,
        actor_id: str | None,
        error: CanonicalDomainError,
    ) -> None:
        try:
            failed = await self.trace_service.fail_trace(
                FailTraceInput(
                    trace_id=context.trace_id,
                    parent_trace_id=context.parent_trace_id,
                    event_type=f"{operation}.failed",
                    actor_id=actor_id,
                    actor_type="user" if actor_id is not None else "system",
                    user_id=_actor_user_id(actor_id),
                    workspace_id=workspace_id,
                    object_id=object_id,
                    object_type=object_type,
                    operation=operation,
                    error=TraceErrorInfo(code=error.code, message=error.safe_message),
                )
            )
        except TracePersistenceError as exc:
            raise CanonicalStorageError("Canonical failure trace persistence failed.") from exc
        await self._publish_trace_marker(failed, actor_id)

    async def _publish_trace_marker(self, trace_event: TraceEvent, actor_id: str | None) -> None:
        if trace_event.workspace_id is None:
            return
        await self.event_bus.publish(
            TraceEventRecorded(
                workspace_id=trace_event.workspace_id,
                actor_id=actor_id,
                trace_id=trace_event.trace_id,
                object_id=trace_event.object_id,
                object_type=trace_event.object_type,
                trace_event_id=trace_event.event_id,
            )
        )


def _actor_user_id(actor_id: str | None) -> uuid.UUID | None:
    if actor_id is None:
        return None
    try:
        return uuid.UUID(actor_id)
    except ValueError:
        return None


def _parse_create_payload(object_type: str, payload: JsonObject) -> PayloadModel:
    model_by_type: dict[str, type[CanonicalInputModel]] = {
        "document": DocumentPayload,
        "chunk": ChunkPayload,
        "note": NotePayload,
        "execution": ExecutionPayload,
    }
    model = model_by_type.get(object_type)
    if model is None:
        raise CanonicalValidationError("Canonical object type is not creatable.")
    try:
        parsed = model.model_validate(payload)
    except ValidationError as exc:
        raise CanonicalValidationError(f"Invalid {object_type} payload.") from exc
    return cast(PayloadModel, parsed)


def _merge_and_validate_payload(
    aggregate: CanonicalAggregate, patch_data: JsonObject
) -> PayloadModel:
    current = _detail_payload(aggregate)
    model_by_type: dict[str, tuple[type[CanonicalInputModel], type[CanonicalInputModel]]] = {
        "document": (DocumentPatch, DocumentPayload),
        "chunk": (ChunkPatch, ChunkPayload),
        "note": (NotePatch, NotePayload),
        "execution": (ExecutionPatch, ExecutionPayload),
    }
    models = model_by_type.get(aggregate.object.object_type)
    if models is None:
        raise CanonicalValidationError("Canonical object payload is not mutable.")
    patch_model, full_model = models
    try:
        patch = patch_model.model_validate(patch_data)
        merged = {**current, **patch.model_dump(exclude_unset=True)}
        parsed = full_model.model_validate(merged)
    except ValidationError as exc:
        raise CanonicalValidationError(f"Invalid {aggregate.object.object_type} payload.") from exc
    return cast(PayloadModel, parsed)


def _new_detail(
    object_id: uuid.UUID, payload: PayloadModel, operation_trace_id: uuid.UUID
) -> CanonicalDocument | CanonicalChunk | CanonicalNote | CanonicalExecution:
    if isinstance(payload, DocumentPayload):
        return CanonicalDocument(
            object_id=object_id,
            display_name=payload.display_name,
            source_type=payload.source_type,
            processing_status=payload.processing_status,
            source_metadata=_json_object(payload.source_metadata),
            legacy_document_id=payload.legacy_document_id,
        )
    if isinstance(payload, ChunkPayload):
        return CanonicalChunk(
            object_id=object_id,
            document_object_id=payload.document_object_id,
            ordered_position=payload.ordered_position,
            content=payload.content,
            source_location=_json_object(payload.source_location),
        )
    if isinstance(payload, NotePayload):
        return CanonicalNote(object_id=object_id, title=payload.title, content=payload.content)
    return CanonicalExecution(
        object_id=object_id,
        execution_type=payload.execution_type,
        status=payload.status,
        started_at=payload.started_at,
        completed_at=payload.completed_at,
        trace_id=payload.trace_id or operation_trace_id,
        inputs_metadata=_json_object(payload.inputs_metadata),
        outputs_metadata=_json_object(payload.outputs_metadata),
        failure=_json_object(payload.failure) if payload.failure is not None else None,
    )


def _detail_payload(aggregate: CanonicalAggregate) -> dict[str, object]:
    detail = aggregate.detail
    if isinstance(detail, CanonicalDocument):
        return {
            "display_name": detail.display_name,
            "source_type": detail.source_type,
            "processing_status": detail.processing_status,
            "source_metadata": detail.source_metadata,
            "legacy_document_id": detail.legacy_document_id,
        }
    if isinstance(detail, CanonicalChunk):
        return {
            "document_object_id": detail.document_object_id,
            "ordered_position": detail.ordered_position,
            "content": detail.content,
            "source_location": detail.source_location,
        }
    if isinstance(detail, CanonicalNote):
        return {"title": detail.title, "content": detail.content}
    if isinstance(detail, CanonicalExecution):
        return {
            "execution_type": detail.execution_type,
            "status": detail.status,
            "started_at": detail.started_at,
            "completed_at": detail.completed_at,
            "trace_id": detail.trace_id,
            "inputs_metadata": detail.inputs_metadata,
            "outputs_metadata": detail.outputs_metadata,
            "failure": detail.failure,
        }
    raise CanonicalValidationError("Relationship payloads use dedicated mutations.")


def _apply_payload(aggregate: CanonicalAggregate, payload: PayloadModel) -> None:
    detail = aggregate.detail
    if isinstance(detail, CanonicalDocument) and isinstance(payload, DocumentPayload):
        detail.display_name = payload.display_name
        detail.source_type = payload.source_type
        detail.processing_status = payload.processing_status
        detail.source_metadata = _json_object(payload.source_metadata)
        detail.legacy_document_id = payload.legacy_document_id
        return
    if isinstance(detail, CanonicalChunk) and isinstance(payload, ChunkPayload):
        detail.ordered_position = payload.ordered_position
        detail.content = payload.content
        detail.source_location = _json_object(payload.source_location)
        return
    if isinstance(detail, CanonicalNote) and isinstance(payload, NotePayload):
        detail.title = payload.title
        detail.content = payload.content
        return
    if isinstance(detail, CanonicalExecution) and isinstance(payload, ExecutionPayload):
        detail.execution_type = payload.execution_type
        detail.status = payload.status
        detail.started_at = payload.started_at
        detail.completed_at = payload.completed_at
        detail.trace_id = payload.trace_id
        detail.inputs_metadata = _json_object(payload.inputs_metadata)
        detail.outputs_metadata = _json_object(payload.outputs_metadata)
        detail.failure = _json_object(payload.failure) if payload.failure is not None else None
        return
    raise CanonicalValidationError("Canonical payload does not match its object type.")


def _execution_events(
    aggregate: CanonicalAggregate,
    *,
    previous_status: str | None,
    actor: str | None,
) -> list[DomainEvent]:
    detail = aggregate.detail
    if not isinstance(detail, CanonicalExecution) or detail.status == previous_status:
        return []
    if detail.status == "running":
        return [
            ExecutionStarted(
                workspace_id=aggregate.object.workspace_id,
                actor_id=actor,
                trace_id=detail.trace_id,
                object_id=aggregate.object.id,
                object_type="execution",
                object_version=aggregate.object.version,
            )
        ]
    if detail.status in {"succeeded", "cancelled"}:
        return [
            ExecutionCompleted(
                workspace_id=aggregate.object.workspace_id,
                actor_id=actor,
                trace_id=detail.trace_id,
                object_id=aggregate.object.id,
                object_type="execution",
                object_version=aggregate.object.version,
                metadata={"status": detail.status},
            )
        ]
    if detail.status == "failed":
        failure = detail.failure or {}
        return [
            ExecutionFailed(
                workspace_id=aggregate.object.workspace_id,
                actor_id=actor,
                trace_id=detail.trace_id,
                object_id=aggregate.object.id,
                object_type="execution",
                object_version=aggregate.object.version,
                error_code=str(failure.get("code", "execution_failed")),
                error_message=str(failure.get("message", "Execution failed.")),
            )
        ]
    return []


def _success_trace_metadata(events: list[DomainEvent]) -> JsonObject:
    if not events:
        return {}
    primary = events[0]
    metadata: JsonObject = {}
    if primary.object_version is not None:
        metadata["newVersion"] = primary.object_version
        metadata["previousVersion"] = max(0, primary.object_version - 1)
    if isinstance(primary, (CanonicalObjectTransitioned, WorkspaceTransitioned)):
        metadata["previousState"] = primary.previous_state
        metadata["currentState"] = primary.current_state
    elif isinstance(primary, (CanonicalObjectDeleted, WorkspaceDeleted)):
        metadata["previousState"] = primary.previous_state
        metadata["currentState"] = LifecycleState.DELETED.value
    return metadata


def _validate_execution(
    status: ExecutionStatus,
    started_at: datetime | None,
    completed_at: datetime | None,
    failure: JsonObject | None,
) -> None:
    if (
        started_at is not None
        and completed_at is not None
        and _as_utc(completed_at) < _as_utc(started_at)
    ):
        raise ValueError("completed_at must not precede started_at")
    if status == "failed" and failure is None:
        raise ValueError("failed executions require failure details")
    if status != "failed" and failure is not None:
        raise ValueError("only failed executions may contain failure details")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_object(value: JsonObject) -> dict[str, object]:
    serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    decoded = json.loads(serialized)
    if not isinstance(decoded, dict):
        raise CanonicalValidationError("Canonical metadata must be a JSON object.")
    return cast(dict[str, object], decoded)


def _actor_uuid(actor_id: str | None) -> uuid.UUID | None:
    if actor_id is None:
        return None
    try:
        return uuid.UUID(actor_id)
    except ValueError:
        return None


__all__ = [
    "CANONICAL_OBJECT_TYPES",
    "DOCUMENT_PROCESSING_STATUSES",
    "EXECUTION_STATUSES",
    "RELATIONSHIP_TYPES",
    "CanonicalObjectType",
    "CanonicalService",
    "CreateObjectInput",
    "CreateRelationshipInput",
    "CreateWorkspaceInput",
    "DocumentPayload",
    "DocumentProcessingStatus",
    "ExecutionPayload",
    "ExecutionStatus",
    "JsonObject",
    "ObjectQueryFilters",
    "RelationshipQueryFilters",
    "RelationshipType",
    "RemoveRelationshipInput",
    "TransitionObjectInput",
    "TransitionWorkspaceInput",
    "UpdateObjectInput",
    "UpdateWorkspaceInput",
    "WorkspaceQueryFilters",
]
