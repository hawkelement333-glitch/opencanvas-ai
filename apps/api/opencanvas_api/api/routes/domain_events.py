from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, status
from pydantic import JsonValue

from opencanvas_api.api.dependencies import (
    PrincipalDep,
    get_domain_event_service,
    require_path_workspace_principal,
)
from opencanvas_api.api.domain_event_schemas import (
    DomainActivityOut,
    DomainEventDeliveryOut,
    DomainEventOut,
    DomainEventProvenanceOut,
    SafeActivityStatus,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.serialization import utc
from opencanvas_api.services.domain_events import (
    ActivityView,
    DomainEventError,
    DomainEventNotFoundError,
    DomainEventService,
    RecordedDomainEvent,
)

router = APIRouter(dependencies=[Depends(require_path_workspace_principal)])
DomainEventServiceDep = Annotated[DomainEventService, Depends(get_domain_event_service)]


@router.get(
    "/workspaces/{workspace_id}/activity",
    response_model=list[DomainActivityOut],
)
async def list_workspace_activity(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    service: DomainEventServiceDep,
    canvas_id: Annotated[uuid.UUID | None, Query(alias="canvasId")] = None,
    subject_id: Annotated[uuid.UUID | None, Query(alias="subjectId")] = None,
    execution_id: Annotated[uuid.UUID | None, Query(alias="executionId")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[DomainActivityOut]:
    return await _activity(
        service,
        user_id=principal.user_id,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
        subject_id=subject_id,
        execution_id=execution_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/activity",
    response_model=list[DomainActivityOut],
)
async def list_canvas_activity(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    principal: PrincipalDep,
    service: DomainEventServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[DomainActivityOut]:
    return await _activity(
        service,
        user_id=principal.user_id,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/workspaces/{workspace_id}/knowledge-graph/entities/{entity_id}/activity",
    response_model=list[DomainActivityOut],
)
async def list_graph_entity_activity(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    principal: PrincipalDep,
    service: DomainEventServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[DomainActivityOut]:
    return await _activity(
        service,
        user_id=principal.user_id,
        workspace_id=workspace_id,
        subject_id=entity_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/workspaces/{workspace_id}/knowledge-graph/relationships/{relationship_id}/activity",
    response_model=list[DomainActivityOut],
)
async def list_graph_relationship_activity(
    workspace_id: uuid.UUID,
    relationship_id: uuid.UUID,
    principal: PrincipalDep,
    service: DomainEventServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[DomainActivityOut]:
    try:
        rows = await service.list_activity(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            relationship_id=relationship_id,
            limit=limit,
            offset=offset,
        )
    except DomainEventError as exc:
        raise _api_error(exc) from exc
    return [_activity_out(row) for row in rows]


@router.get(
    "/workspaces/{workspace_id}/agent-executions/{execution_id}/activity",
    response_model=list[DomainActivityOut],
)
async def list_execution_activity(
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    principal: PrincipalDep,
    service: DomainEventServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[DomainActivityOut]:
    return await _activity(
        service,
        user_id=principal.user_id,
        workspace_id=workspace_id,
        execution_id=execution_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/workspaces/{workspace_id}/events/{event_id}",
    response_model=DomainEventOut,
)
async def get_domain_event(
    workspace_id: uuid.UUID,
    event_id: uuid.UUID,
    principal: PrincipalDep,
    service: DomainEventServiceDep,
) -> DomainEventOut:
    try:
        record = await service.get_owned_event(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            event_id=event_id,
        )
    except DomainEventError as exc:
        raise _api_error(exc) from exc
    return _event_out(record)


@router.get(
    "/workspaces/{workspace_id}/events/{event_id}/delivery",
    response_model=DomainEventDeliveryOut,
)
async def get_domain_event_delivery(
    workspace_id: uuid.UUID,
    event_id: uuid.UUID,
    principal: PrincipalDep,
    service: DomainEventServiceDep,
) -> DomainEventDeliveryOut:
    try:
        record = await service.get_owned_event(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            event_id=event_id,
        )
    except DomainEventError as exc:
        raise _api_error(exc) from exc
    return _delivery_out(record)


async def _activity(
    service: DomainEventService,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
    execution_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> list[DomainActivityOut]:
    try:
        rows = await service.list_activity(
            user_id=user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            subject_id=subject_id,
            execution_id=execution_id,
            limit=limit,
            offset=offset,
        )
    except DomainEventError as exc:
        raise _api_error(exc) from exc
    return [_activity_out(row) for row in rows]


def _event_out(record: RecordedDomainEvent) -> DomainEventOut:
    event = record.event
    provenance = record.provenance
    return DomainEventOut(
        event_id=event.event_id,
        event_type=event.event_type,
        registry_version=event.registry_version,
        schema_version=event.schema_version,
        user_id=event.user_id,
        workspace_id=event.workspace_id,
        canvas_id=event.canvas_id,
        sequence=event.sequence,
        subject_kind=event.subject_kind,
        subject_id=event.subject_id,
        related_id=event.related_id,
        actor_user_id=event.actor_user_id,
        execution_id=event.execution_id,
        graph_revision=event.graph_revision,
        occurred_at=utc(event.occurred_at),
        payload=cast(dict[str, JsonValue], event.payload),
        payload_digest=event.payload_digest,
        trace_id=event.trace_id,
        audit_event_id=event.audit_event_id,
        provenance=DomainEventProvenanceOut(
            provenance_id=provenance.provenance_id,
            origin_type=cast(
                Literal[
                    "authenticated_user",
                    "canonical_service",
                    "controlled_execution",
                    "reserved_future_contract",
                ],
                provenance.origin_type,
            ),
            actor_user_id=provenance.actor_user_id,
            trace_id=provenance.trace_id,
            audit_event_id=provenance.audit_event_id,
            execution_id=provenance.execution_id,
            graph_relationship_id=provenance.graph_relationship_id,
            graph_history_id=provenance.graph_history_id,
            effect_id=provenance.effect_id,
            rollback_result_id=provenance.rollback_result_id,
            provenance_digest=provenance.provenance_digest,
        ),
        delivery=_delivery_out(record),
    )


def _delivery_out(record: RecordedDomainEvent) -> DomainEventDeliveryOut:
    outbox = record.outbox
    return DomainEventDeliveryOut(
        status=_status(outbox.delivery_state),
        attempt_count=outbox.attempt_count,
        max_attempts=outbox.max_attempts,
        eligible_at=utc(outbox.eligible_at),
        failure_classification=outbox.failure_classification,
        completed_at=utc(outbox.completed_at) if outbox.completed_at else None,
        terminal_at=utc(outbox.terminal_at) if outbox.terminal_at else None,
    )


def _activity_out(view: ActivityView) -> DomainActivityOut:
    event = view.event
    return DomainActivityOut(
        event_id=event.event_id,
        event_type=event.event_type,
        sequence=event.sequence,
        workspace_id=event.workspace_id,
        canvas_id=event.canvas_id,
        subject_kind=event.subject_kind,
        subject_id=event.subject_id,
        actor_user_id=event.actor_user_id,
        execution_id=event.execution_id,
        graph_revision=event.graph_revision,
        trace_id=event.trace_id,
        occurred_at=utc(event.occurred_at),
        status=view.status,
        projected=view.projected,
    )


def _status(value: str) -> SafeActivityStatus:
    mapping: dict[str, SafeActivityStatus] = {
        "pending": "pending_delivery",
        "delivering": "actively_delivering",
        "delivered": "delivered",
        "retry_wait": "retry_waiting",
        "terminal_failure": "terminal_delivery_failure",
    }
    if value not in mapping:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "event_state_inconsistent",
            "Event delivery state is unavailable.",
        )
    return mapping[value]


def _api_error(error: DomainEventError) -> ApiError:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, DomainEventNotFoundError)
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return ApiError(status_code, error.code, error.safe_message)


__all__ = ["router"]
