from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    PrincipalDep,
    get_knowledge_graph_service,
    get_session,
    require_path_workspace_principal,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.knowledge_graph_schemas import (
    GraphEntityReferenceOut,
    GraphHistoryOut,
    GraphProvenanceOut,
    GraphRelationshipCreateIn,
    GraphRelationshipOut,
    GraphRelationshipTransitionIn,
)
from opencanvas_api.api.serialization import utc
from opencanvas_api.db.models import CanonicalRelationshipHistory
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalDomainError,
    CanonicalNotFoundError,
    CanonicalStorageError,
    CanonicalValidationError,
)
from opencanvas_api.services.knowledge_graph import (
    CreateGraphRelationship,
    DeactivateGraphRelationship,
    GraphEntityKind,
    GraphEntityReference,
    GraphHistoryState,
    GraphRelationshipRecord,
    GraphRelationshipType,
    KnowledgeGraphService,
)

router = APIRouter(dependencies=[Depends(require_path_workspace_principal)])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
GraphServiceDep = Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)]


@router.post(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/relationships",
    response_model=GraphRelationshipOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_graph_relationship(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: GraphRelationshipCreateIn,
    principal: PrincipalDep,
    service: GraphServiceDep,
    session: SessionDep,
) -> GraphRelationshipOut:
    record = await _mutate(
        service.create_relationship(
            CreateGraphRelationship(
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                relationship_type=payload.relationship_type,
                source=GraphEntityReference(
                    kind=payload.source.kind,
                    object_id=payload.source.object_id,
                ),
                target=GraphEntityReference(
                    kind=payload.target.kind,
                    object_id=payload.target.object_id,
                ),
                idempotency_key=payload.idempotency_key,
                parent_trace_id=payload.parent_trace_id,
            )
        ),
        session,
    )
    return _relationship_out(record)


@router.get(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/"
    "entities/{entity_id}/relationships",
    response_model=list[GraphRelationshipOut],
)
async def list_graph_entity_relationships(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    entity_id: uuid.UUID,
    principal: PrincipalDep,
    service: GraphServiceDep,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[GraphRelationshipOut]:
    records = await _read(
        service.list_entity_relationships(
            principal.user_id,
            workspace_id,
            canvas_id,
            entity_id,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
    )
    return [_relationship_out(record) for record in records]


@router.get(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/"
    "relationships/{relationship_id}",
    response_model=GraphRelationshipOut,
)
async def get_graph_relationship(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    relationship_id: uuid.UUID,
    principal: PrincipalDep,
    service: GraphServiceDep,
) -> GraphRelationshipOut:
    return _relationship_out(
        await _read(
            service.get_relationship(
                principal.user_id,
                workspace_id,
                canvas_id,
                relationship_id,
            )
        )
    )


@router.get(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/"
    "relationships/{relationship_id}/history",
    response_model=list[GraphHistoryOut],
)
async def list_graph_relationship_history(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    relationship_id: uuid.UUID,
    principal: PrincipalDep,
    service: GraphServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[GraphHistoryOut]:
    history = await _read(
        service.list_history(
            principal.user_id,
            workspace_id,
            canvas_id,
            relationship_id,
            limit=limit,
            offset=offset,
        )
    )
    return [_history_out(item) for item in history]


@router.post(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/"
    "relationships/{relationship_id}/transition",
    response_model=GraphRelationshipOut,
)
async def transition_graph_relationship(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    relationship_id: uuid.UUID,
    payload: GraphRelationshipTransitionIn,
    principal: PrincipalDep,
    service: GraphServiceDep,
    session: SessionDep,
) -> GraphRelationshipOut:
    record = await _mutate(
        service.deactivate_relationship(
            DeactivateGraphRelationship(
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                relationship_id=relationship_id,
                expected_version=payload.expected_version,
                idempotency_key=payload.idempotency_key,
                target_state=payload.target_state,
                reason_code=payload.reason_code,
                parent_trace_id=payload.parent_trace_id,
            )
        ),
        session,
    )
    return _relationship_out(record)


async def _mutate[ResultT](awaitable: Awaitable[ResultT], session: AsyncSession) -> ResultT:
    try:
        result = await awaitable
    except CanonicalDomainError as exc:
        await _commit(session)
        raise _api_error(exc) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "knowledge_graph_storage_failed",
            "Knowledge graph persistence is temporarily unavailable.",
        ) from exc
    await _commit(session)
    return result


async def _read[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except CanonicalDomainError as exc:
        raise _api_error(exc) from exc


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "knowledge_graph_storage_failed",
            "Knowledge graph persistence is temporarily unavailable.",
        ) from exc


def _api_error(error: CanonicalDomainError) -> ApiError:
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


def _relationship_out(record: GraphRelationshipRecord) -> GraphRelationshipOut:
    return GraphRelationshipOut(
        relationship_id=record.graph.relationship_id,
        relationship_type=cast(GraphRelationshipType, record.relationship.relationship_type),
        source=GraphEntityReferenceOut(
            kind=cast(GraphEntityKind, record.source.entity_kind),
            object_id=record.source.object_id,
        ),
        target=GraphEntityReferenceOut(
            kind=cast(GraphEntityKind, record.target.entity_kind),
            object_id=record.target.object_id,
        ),
        user_id=record.graph.user_id,
        workspace_id=record.graph.workspace_id,
        canvas_id=record.graph.canvas_id,
        version=record.object.version,
        lifecycle_state=record.object.lifecycle_state,
        graph_revision=record.current_history.graph_revision,
        canonical_digest=record.graph.canonical_digest,
        current_state=cast(GraphHistoryState, record.current_history.state),
        provenance=GraphProvenanceOut(
            provenance_id=record.provenance.provenance_id,
            origin_type=cast(
                Literal[
                    "user_created",
                    "imported_canonical",
                    "citation_derived",
                    "controlled_agent_approved",
                    "deterministic_rule",
                ],
                record.provenance.origin_type,
            ),
            actor_user_id=record.provenance.actor_user_id,
            execution_id=record.provenance.execution_id,
            source_reference_id=record.provenance.source_reference_id,
            rule_id=record.provenance.rule_id,
            rule_version=record.provenance.rule_version,
            trace_id=record.provenance.trace_id,
            provenance_digest=record.provenance.provenance_digest,
            created_at=utc(record.provenance.created_at),
        ),
        created_at=utc(record.graph.created_at),
        replayed=record.replayed,
    )


def _history_out(history: CanonicalRelationshipHistory) -> GraphHistoryOut:
    return GraphHistoryOut(
        history_id=history.history_id,
        state=cast(GraphHistoryState, history.state),
        reason_code=history.reason_code,
        actor_user_id=history.actor_user_id,
        trace_id=history.trace_id,
        graph_revision=history.graph_revision,
        previous_history_id=history.previous_history_id,
        created_at=utc(history.created_at),
    )


__all__ = ["router"]
