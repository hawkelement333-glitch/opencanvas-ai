from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import PrincipalDep, get_session, get_trace_service
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.serialization import utc
from opencanvas_api.api.trace_schemas import TraceErrorOut, TraceEventOut
from opencanvas_api.db.models import TraceEvent, Workspace
from opencanvas_api.services.authorization import AuthorizationError, require_trace_workspace
from opencanvas_api.services.trace import (
    ActorType,
    TraceQueryFilters,
    TraceService,
    TraceStatus,
)

router = APIRouter()
TraceServiceDep = Annotated[TraceService, Depends(get_trace_service)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/traces/{trace_id}", response_model=list[TraceEventOut])
async def get_trace(
    trace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    trace_service: TraceServiceDep,
) -> list[TraceEventOut]:
    try:
        await require_trace_workspace(session, principal, trace_id)
    except AuthorizationError as exc:
        raise ApiError(
            http_status.HTTP_404_NOT_FOUND, "trace_not_found", "Trace not found."
        ) from exc
    return [_trace_event_out(event) for event in await trace_service.get_trace(trace_id)]


@router.get("/trace-events", response_model=list[TraceEventOut])
async def query_trace_events(
    trace_service: TraceServiceDep,
    principal: PrincipalDep,
    session: SessionDep,
    trace_id: Annotated[uuid.UUID | None, Query(alias="traceId")] = None,
    parent_trace_id: Annotated[uuid.UUID | None, Query(alias="parentTraceId")] = None,
    workspace_id: Annotated[uuid.UUID | None, Query(alias="workspaceId")] = None,
    object_id: Annotated[uuid.UUID | None, Query(alias="objectId")] = None,
    event_type: Annotated[
        str | None, Query(alias="eventType", min_length=1, max_length=120)
    ] = None,
    actor_type: Annotated[ActorType | None, Query(alias="actorType")] = None,
    status: TraceStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[TraceEventOut]:
    owned_workspace_ids = list(
        (
            await session.scalars(
                select(Workspace.id).where(
                    Workspace.owner_id == principal.user_id,
                    Workspace.deleted_at.is_(None),
                )
            )
        ).all()
    )
    if workspace_id is not None and workspace_id not in owned_workspace_ids:
        raise ApiError(http_status.HTTP_404_NOT_FOUND, "trace_not_found", "Trace not found.")
    events = await trace_service.query_trace_events(
        TraceQueryFilters(
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            workspace_id=workspace_id,
            workspace_ids=None if workspace_id is not None else owned_workspace_ids,
            object_id=object_id,
            event_type=event_type,
            actor_type=actor_type,
            status=status,
            limit=limit,
            offset=offset,
        )
    )
    return [_trace_event_out(event) for event in events]


def _trace_event_out(event: TraceEvent) -> TraceEventOut:
    error = None
    if event.error_payload is not None:
        error = TraceErrorOut.model_validate(event.error_payload)
    return TraceEventOut(
        event_id=event.event_id,
        trace_id=event.trace_id,
        parent_trace_id=event.parent_trace_id,
        timestamp=utc(event.occurred_at),
        event_type=event.event_type,
        actor_id=event.actor_id,
        actor_type=cast(ActorType, event.actor_type),
        user_id=event.user_id,
        workspace_id=event.workspace_id,
        object_id=event.object_id,
        object_type=event.object_type,
        operation=event.operation,
        status=cast(TraceStatus, event.status),
        metadata=cast(dict[str, JsonValue], event.metadata_payload),
        error=error,
    )
