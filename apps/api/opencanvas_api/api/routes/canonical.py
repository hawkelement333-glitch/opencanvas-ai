from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, TypedDict, cast

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.canonical_schemas import (
    CanonicalObjectType,
    ChunkCreate,
    ChunkOut,
    ChunkUpdate,
    DocumentCreate,
    DocumentOut,
    DocumentProcessingStatus,
    DocumentUpdate,
    ExecutionCreate,
    ExecutionOut,
    ExecutionStatus,
    ExecutionUpdate,
    JsonObject,
    LifecycleState,
    LifecycleTransition,
    NoteCreate,
    NoteOut,
    NoteUpdate,
    RelationshipCreate,
    RelationshipOut,
    RelationshipType,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from opencanvas_api.api.dependencies import get_canonical_service, get_session
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.serialization import utc
from opencanvas_api.db.models import (
    CanonicalChunk,
    CanonicalDocument,
    CanonicalExecution,
    CanonicalNote,
    CanonicalObject,
    CanonicalRelationship,
    Workspace,
)
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalDomainError,
    CanonicalNotFoundError,
    CanonicalStorageError,
    CanonicalValidationError,
)
from opencanvas_api.services.canonical.lifecycle import (
    LifecycleState as ServiceLifecycleState,
)
from opencanvas_api.services.canonical.repository import CanonicalAggregate
from opencanvas_api.services.canonical.service import (
    CanonicalService,
    CreateObjectInput,
    CreateRelationshipInput,
    CreateWorkspaceInput,
    ObjectQueryFilters,
    RelationshipQueryFilters,
    RemoveRelationshipInput,
    TransitionObjectInput,
    TransitionWorkspaceInput,
    UpdateObjectInput,
    UpdateWorkspaceInput,
    WorkspaceQueryFilters,
)

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
CanonicalServiceDep = Annotated[CanonicalService, Depends(get_canonical_service)]


class _ObjectFields(TypedDict):
    id: uuid.UUID
    workspace_id: uuid.UUID
    version: int
    lifecycle_state: LifecycleState
    metadata: JsonObject
    created_at: datetime
    updated_at: datetime


@router.post(
    "/workspaces",
    response_model=WorkspaceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    payload: WorkspaceCreate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> WorkspaceOut:
    workspace = await _mutate(
        service.create_workspace(CreateWorkspaceInput.model_validate(payload.model_dump())),
        session,
    )
    return _workspace_out(workspace)


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    service: CanonicalServiceDep,
    owner_id: Annotated[uuid.UUID | None, Query(alias="ownerId")] = None,
    lifecycle_state: Annotated[LifecycleState | None, Query(alias="lifecycleState")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[WorkspaceOut]:
    workspaces = await _read(
        service.list_workspaces(
            WorkspaceQueryFilters(
                owner_id=owner_id,
                lifecycle_state=_service_state(lifecycle_state),
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
            )
        )
    )
    return [_workspace_out(workspace) for workspace in workspaces]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: uuid.UUID,
    service: CanonicalServiceDep,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> WorkspaceOut:
    return _workspace_out(
        await _read(service.get_workspace(workspace_id, include_deleted=include_deleted))
    )


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> WorkspaceOut:
    values = payload.model_dump(exclude_unset=True)
    values["workspace_id"] = workspace_id
    workspace = await _mutate(
        service.update_workspace(UpdateWorkspaceInput.model_validate(values)),
        session,
    )
    return _workspace_out(workspace)


@router.post("/workspaces/{workspace_id}/transition", response_model=WorkspaceOut)
async def transition_workspace(
    workspace_id: uuid.UUID,
    payload: LifecycleTransition,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> WorkspaceOut:
    workspace = await _mutate(
        service.transition_workspace(
            TransitionWorkspaceInput(
                workspace_id=workspace_id,
                expected_version=payload.expected_version,
                target_state=ServiceLifecycleState(payload.target_state),
                actor_id=payload.actor_id,
                parent_trace_id=payload.parent_trace_id,
            )
        ),
        session,
    )
    return _workspace_out(workspace)


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    workspace_id: uuid.UUID,
    payload: DocumentCreate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> DocumentOut:
    return await _create_object(workspace_id, "document", payload, service, session, _document_out)


@router.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    workspace_id: uuid.UUID,
    service: CanonicalServiceDep,
    lifecycle_state: Annotated[LifecycleState | None, Query(alias="lifecycleState")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[DocumentOut]:
    return await _list_objects(
        workspace_id,
        "document",
        lifecycle_state,
        include_deleted,
        limit,
        offset,
        service,
        _document_out,
    )


@router.get("/workspaces/{workspace_id}/documents/{object_id}", response_model=DocumentOut)
async def get_document(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    service: CanonicalServiceDep,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> DocumentOut:
    return _document_out(
        await _get_typed_object(
            service, workspace_id, object_id, "document", include_deleted=include_deleted
        )
    )


@router.patch("/workspaces/{workspace_id}/documents/{object_id}", response_model=DocumentOut)
async def update_document(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: DocumentUpdate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> DocumentOut:
    return await _update_object(
        workspace_id, object_id, "document", payload, service, session, _document_out
    )


@router.post(
    "/workspaces/{workspace_id}/documents/{object_id}/transition",
    response_model=DocumentOut,
)
async def transition_document(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: LifecycleTransition,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> DocumentOut:
    return await _transition_object(
        workspace_id, object_id, "document", payload, service, session, _document_out
    )


@router.post(
    "/workspaces/{workspace_id}/chunks",
    response_model=ChunkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_chunk(
    workspace_id: uuid.UUID,
    payload: ChunkCreate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> ChunkOut:
    return await _create_object(workspace_id, "chunk", payload, service, session, _chunk_out)


@router.get("/workspaces/{workspace_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    workspace_id: uuid.UUID,
    service: CanonicalServiceDep,
    lifecycle_state: Annotated[LifecycleState | None, Query(alias="lifecycleState")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[ChunkOut]:
    return await _list_objects(
        workspace_id,
        "chunk",
        lifecycle_state,
        include_deleted,
        limit,
        offset,
        service,
        _chunk_out,
    )


@router.get("/workspaces/{workspace_id}/chunks/{object_id}", response_model=ChunkOut)
async def get_chunk(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    service: CanonicalServiceDep,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> ChunkOut:
    return _chunk_out(
        await _get_typed_object(
            service, workspace_id, object_id, "chunk", include_deleted=include_deleted
        )
    )


@router.patch("/workspaces/{workspace_id}/chunks/{object_id}", response_model=ChunkOut)
async def update_chunk(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: ChunkUpdate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> ChunkOut:
    return await _update_object(
        workspace_id, object_id, "chunk", payload, service, session, _chunk_out
    )


@router.post(
    "/workspaces/{workspace_id}/chunks/{object_id}/transition",
    response_model=ChunkOut,
)
async def transition_chunk(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: LifecycleTransition,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> ChunkOut:
    return await _transition_object(
        workspace_id, object_id, "chunk", payload, service, session, _chunk_out
    )


@router.post(
    "/workspaces/{workspace_id}/notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_note(
    workspace_id: uuid.UUID,
    payload: NoteCreate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> NoteOut:
    return await _create_object(workspace_id, "note", payload, service, session, _note_out)


@router.get("/workspaces/{workspace_id}/notes", response_model=list[NoteOut])
async def list_notes(
    workspace_id: uuid.UUID,
    service: CanonicalServiceDep,
    lifecycle_state: Annotated[LifecycleState | None, Query(alias="lifecycleState")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[NoteOut]:
    return await _list_objects(
        workspace_id,
        "note",
        lifecycle_state,
        include_deleted,
        limit,
        offset,
        service,
        _note_out,
    )


@router.get("/workspaces/{workspace_id}/notes/{object_id}", response_model=NoteOut)
async def get_note(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    service: CanonicalServiceDep,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> NoteOut:
    return _note_out(
        await _get_typed_object(
            service, workspace_id, object_id, "note", include_deleted=include_deleted
        )
    )


@router.patch("/workspaces/{workspace_id}/notes/{object_id}", response_model=NoteOut)
async def update_note(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: NoteUpdate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> NoteOut:
    return await _update_object(
        workspace_id, object_id, "note", payload, service, session, _note_out
    )


@router.post(
    "/workspaces/{workspace_id}/notes/{object_id}/transition",
    response_model=NoteOut,
)
async def transition_note(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: LifecycleTransition,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> NoteOut:
    return await _transition_object(
        workspace_id, object_id, "note", payload, service, session, _note_out
    )


@router.post(
    "/workspaces/{workspace_id}/executions",
    response_model=ExecutionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_execution(
    workspace_id: uuid.UUID,
    payload: ExecutionCreate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> ExecutionOut:
    return await _create_object(
        workspace_id, "execution", payload, service, session, _execution_out
    )


@router.get("/workspaces/{workspace_id}/executions", response_model=list[ExecutionOut])
async def list_executions(
    workspace_id: uuid.UUID,
    service: CanonicalServiceDep,
    lifecycle_state: Annotated[LifecycleState | None, Query(alias="lifecycleState")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[ExecutionOut]:
    return await _list_objects(
        workspace_id,
        "execution",
        lifecycle_state,
        include_deleted,
        limit,
        offset,
        service,
        _execution_out,
    )


@router.get("/workspaces/{workspace_id}/executions/{object_id}", response_model=ExecutionOut)
async def get_execution(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    service: CanonicalServiceDep,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
) -> ExecutionOut:
    return _execution_out(
        await _get_typed_object(
            service, workspace_id, object_id, "execution", include_deleted=include_deleted
        )
    )


@router.patch("/workspaces/{workspace_id}/executions/{object_id}", response_model=ExecutionOut)
async def update_execution(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: ExecutionUpdate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> ExecutionOut:
    return await _update_object(
        workspace_id, object_id, "execution", payload, service, session, _execution_out
    )


@router.post(
    "/workspaces/{workspace_id}/executions/{object_id}/transition",
    response_model=ExecutionOut,
)
async def transition_execution(
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    payload: LifecycleTransition,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> ExecutionOut:
    return await _transition_object(
        workspace_id, object_id, "execution", payload, service, session, _execution_out
    )


@router.post(
    "/workspaces/{workspace_id}/relationships",
    response_model=RelationshipOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_relationship(
    workspace_id: uuid.UUID,
    payload: RelationshipCreate,
    service: CanonicalServiceDep,
    session: SessionDep,
) -> RelationshipOut:
    relationship = await _mutate(
        service.create_relationship(
            CreateRelationshipInput(
                workspace_id=workspace_id,
                relationship_type=payload.relationship_type,
                source_object_id=payload.source_object_id,
                target_object_id=payload.target_object_id,
                metadata=payload.metadata,
                actor_id=payload.actor_id,
                parent_trace_id=payload.parent_trace_id,
            )
        ),
        session,
    )
    return _relationship_out(relationship)


@router.get(
    "/workspaces/{workspace_id}/relationships",
    response_model=list[RelationshipOut],
)
async def list_relationships(
    workspace_id: uuid.UUID,
    service: CanonicalServiceDep,
    relationship_type: Annotated[RelationshipType | None, Query(alias="relationshipType")] = None,
    source_object_id: Annotated[uuid.UUID | None, Query(alias="sourceId")] = None,
    target_object_id: Annotated[uuid.UUID | None, Query(alias="targetId")] = None,
    include_deleted: Annotated[bool, Query(alias="includeDeleted")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[RelationshipOut]:
    relationships = await _read(
        service.list_relationships(
            workspace_id,
            RelationshipQueryFilters(
                relationship_type=relationship_type,
                source_object_id=source_object_id,
                target_object_id=target_object_id,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
            ),
        )
    )
    return [_relationship_out(relationship) for relationship in relationships]


@router.delete(
    "/workspaces/{workspace_id}/relationships/{relationship_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_relationship(
    workspace_id: uuid.UUID,
    relationship_id: uuid.UUID,
    service: CanonicalServiceDep,
    session: SessionDep,
    expected_version: Annotated[int, Query(alias="expectedVersion", ge=1)],
    actor_id: Annotated[str | None, Query(alias="actorId", min_length=1, max_length=255)] = None,
    parent_trace_id: Annotated[uuid.UUID | None, Query(alias="parentTraceId")] = None,
) -> Response:
    await _mutate(
        service.remove_relationship(
            RemoveRelationshipInput(
                workspace_id=workspace_id,
                relationship_id=relationship_id,
                expected_version=expected_version,
                actor_id=actor_id,
                parent_trace_id=parent_trace_id,
            )
        ),
        session,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _create_object[OutputT](
    workspace_id: uuid.UUID,
    object_type: CanonicalObjectType,
    payload: DocumentCreate | ChunkCreate | NoteCreate | ExecutionCreate,
    service: CanonicalService,
    session: AsyncSession,
    serializer: Callable[[CanonicalAggregate], OutputT],
) -> OutputT:
    detail = payload.model_dump(
        mode="json",
        exclude={"actor_id", "parent_trace_id", "metadata"},
    )
    aggregate = await _mutate(
        service.create_object(
            CreateObjectInput(
                workspace_id=workspace_id,
                object_type=object_type,
                payload=cast(JsonObject, detail),
                metadata=payload.metadata,
                actor_id=payload.actor_id,
                parent_trace_id=payload.parent_trace_id,
            )
        ),
        session,
    )
    return serializer(aggregate)


async def _list_objects[OutputT](
    workspace_id: uuid.UUID,
    object_type: CanonicalObjectType,
    lifecycle_state: LifecycleState | None,
    include_deleted: bool,
    limit: int,
    offset: int,
    service: CanonicalService,
    serializer: Callable[[CanonicalAggregate], OutputT],
) -> list[OutputT]:
    aggregates = await _read(
        service.list_objects(
            workspace_id,
            ObjectQueryFilters(
                object_type=object_type,
                lifecycle_state=_service_state(lifecycle_state),
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
            ),
        )
    )
    return [serializer(aggregate) for aggregate in aggregates]


async def _get_typed_object(
    service: CanonicalService,
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    expected_type: CanonicalObjectType,
    *,
    include_deleted: bool,
) -> CanonicalAggregate:
    aggregate = await _read(
        service.get_object(workspace_id, object_id, include_deleted=include_deleted)
    )
    _assert_object_type(aggregate, expected_type)
    return aggregate


async def _update_object[OutputT](
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    object_type: CanonicalObjectType,
    payload: DocumentUpdate | ChunkUpdate | NoteUpdate | ExecutionUpdate,
    service: CanonicalService,
    session: AsyncSession,
    serializer: Callable[[CanonicalAggregate], OutputT],
) -> OutputT:
    await _guard_mutation_type(service, workspace_id, object_id, object_type)
    context_fields = {"expected_version", "actor_id", "parent_trace_id", "metadata"}
    detail_fields = payload.model_fields_set - context_fields
    detail = payload.model_dump(mode="json", include=detail_fields, exclude_unset=True)
    values: dict[str, object] = {
        "workspace_id": workspace_id,
        "object_id": object_id,
        "expected_version": payload.expected_version,
        "actor_id": payload.actor_id,
        "parent_trace_id": payload.parent_trace_id,
    }
    if detail:
        values["payload"] = detail
    if "metadata" in payload.model_fields_set:
        values["metadata"] = payload.metadata
    aggregate = await _mutate(
        service.update_object(UpdateObjectInput.model_validate(values)),
        session,
    )
    return serializer(aggregate)


async def _transition_object[OutputT](
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    object_type: CanonicalObjectType,
    payload: LifecycleTransition,
    service: CanonicalService,
    session: AsyncSession,
    serializer: Callable[[CanonicalAggregate], OutputT],
) -> OutputT:
    await _guard_mutation_type(service, workspace_id, object_id, object_type)
    aggregate = await _mutate(
        service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=object_id,
                expected_version=payload.expected_version,
                target_state=ServiceLifecycleState(payload.target_state),
                actor_id=payload.actor_id,
                parent_trace_id=payload.parent_trace_id,
            )
        ),
        session,
    )
    return serializer(aggregate)


async def _guard_mutation_type(
    service: CanonicalService,
    workspace_id: uuid.UUID,
    object_id: uuid.UUID,
    expected_type: CanonicalObjectType,
) -> None:
    try:
        aggregate = await service.get_object(workspace_id, object_id, include_deleted=True)
    except CanonicalNotFoundError:
        # Let the traced mutation repeat the lookup so its failed event is persisted.
        return
    except CanonicalDomainError as exc:
        raise _canonical_api_error(exc) from exc
    _assert_object_type(aggregate, expected_type)


def _assert_object_type(aggregate: CanonicalAggregate, expected_type: CanonicalObjectType) -> None:
    if aggregate.object.object_type != expected_type:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "canonical_not_found",
            f"Canonical {expected_type} not found in this workspace.",
        )


async def _mutate[ResultT](awaitable: Awaitable[ResultT], session: AsyncSession) -> ResultT:
    try:
        result = await awaitable
    except CanonicalDomainError as exc:
        # The service rolls back only its domain savepoint and leaves start/failed Trace
        # records in a clean outer transaction. Commit them before returning the safe error.
        await _commit(session)
        raise _canonical_api_error(exc) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "canonical_storage_failed",
            "Canonical persistence is temporarily unavailable.",
        ) from exc
    await _commit(session)
    return result


async def _read[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except CanonicalDomainError as exc:
        raise _canonical_api_error(exc) from exc


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "canonical_storage_failed",
            "Canonical persistence is temporarily unavailable.",
        ) from exc


def _canonical_api_error(error: CanonicalDomainError) -> ApiError:
    if isinstance(error, CanonicalNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, CanonicalConflictError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(error, CanonicalValidationError):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, CanonicalStorageError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ApiError(status_code, error.code, error.safe_message)


def _service_state(value: LifecycleState | None) -> ServiceLifecycleState | None:
    return ServiceLifecycleState(value) if value is not None else None


def _workspace_out(workspace: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        owner_id=workspace.owner_id,
        version=workspace.version,
        lifecycle_state=cast(LifecycleState, workspace.lifecycle_state),
        metadata=_json_object(workspace.metadata_payload),
        legacy_canvas_id=workspace.legacy_canvas_id,
        created_at=utc(workspace.created_at),
        updated_at=utc(workspace.updated_at),
    )


def _document_out(aggregate: CanonicalAggregate) -> DocumentOut:
    canonical_object = _expect_object_type(aggregate.object, "document")
    detail = aggregate.detail
    if not isinstance(detail, CanonicalDocument):
        raise TypeError("Canonical document detail is invalid.")
    return DocumentOut(
        **_object_fields(canonical_object),
        object_type="document",
        display_name=detail.display_name,
        source_type=detail.source_type,
        processing_status=cast(DocumentProcessingStatus, detail.processing_status),
        source_metadata=_json_object(detail.source_metadata),
        legacy_document_id=detail.legacy_document_id,
    )


def _chunk_out(aggregate: CanonicalAggregate) -> ChunkOut:
    canonical_object = _expect_object_type(aggregate.object, "chunk")
    detail = aggregate.detail
    if not isinstance(detail, CanonicalChunk):
        raise TypeError("Canonical chunk detail is invalid.")
    return ChunkOut(
        **_object_fields(canonical_object),
        object_type="chunk",
        document_object_id=detail.document_object_id,
        ordered_position=detail.ordered_position,
        content=detail.content,
        source_location=_json_object(detail.source_location),
    )


def _note_out(aggregate: CanonicalAggregate) -> NoteOut:
    canonical_object = _expect_object_type(aggregate.object, "note")
    detail = aggregate.detail
    if not isinstance(detail, CanonicalNote):
        raise TypeError("Canonical note detail is invalid.")
    return NoteOut(
        **_object_fields(canonical_object),
        object_type="note",
        title=detail.title,
        content=detail.content,
    )


def _execution_out(aggregate: CanonicalAggregate) -> ExecutionOut:
    canonical_object = _expect_object_type(aggregate.object, "execution")
    detail = aggregate.detail
    if not isinstance(detail, CanonicalExecution):
        raise TypeError("Canonical execution detail is invalid.")
    return ExecutionOut(
        **_object_fields(canonical_object),
        object_type="execution",
        execution_type=detail.execution_type,
        status=cast(ExecutionStatus, detail.status),
        started_at=utc(detail.started_at) if detail.started_at is not None else None,
        completed_at=utc(detail.completed_at) if detail.completed_at is not None else None,
        trace_id=detail.trace_id,
        inputs_metadata=_json_object(detail.inputs_metadata),
        outputs_metadata=_json_object(detail.outputs_metadata),
        failure=_json_object(detail.failure) if detail.failure is not None else None,
    )


def _relationship_out(aggregate: CanonicalAggregate) -> RelationshipOut:
    canonical_object = _expect_object_type(aggregate.object, "relationship")
    detail = aggregate.detail
    if not isinstance(detail, CanonicalRelationship):
        raise TypeError("Canonical relationship detail is invalid.")
    return RelationshipOut(
        **_object_fields(canonical_object),
        object_type="relationship",
        relationship_type=cast(RelationshipType, detail.relationship_type),
        source_object_id=detail.source_object_id,
        target_object_id=detail.target_object_id,
        created_by=detail.created_by,
        trace_id=detail.trace_id,
    )


def _object_fields(canonical_object: CanonicalObject) -> _ObjectFields:
    return {
        "id": canonical_object.id,
        "workspace_id": canonical_object.workspace_id,
        "version": canonical_object.version,
        "lifecycle_state": cast(LifecycleState, canonical_object.lifecycle_state),
        "metadata": _json_object(canonical_object.metadata_payload),
        "created_at": utc(canonical_object.created_at),
        "updated_at": utc(canonical_object.updated_at),
    }


def _expect_object_type(
    canonical_object: CanonicalObject, expected: CanonicalObjectType
) -> CanonicalObject:
    if canonical_object.object_type != expected:
        raise TypeError(f"Expected a canonical {expected} object.")
    return canonical_object


def _json_object(value: dict[str, object]) -> JsonObject:
    return cast(dict[str, JsonValue], value)


__all__ = ["router"]
