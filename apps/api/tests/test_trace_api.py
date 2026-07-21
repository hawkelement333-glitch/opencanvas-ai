from __future__ import annotations

import uuid

import httpx

from opencanvas_api.db.models import SYSTEM_WORKSPACE_ID
from opencanvas_api.db.session import Database
from opencanvas_api.services.trace import (
    FailTraceInput,
    StartTraceInput,
    TraceErrorInfo,
    TraceService,
)


async def test_trace_read_api_serializes_and_filters_events(
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
) -> None:
    workspace_id = SYSTEM_WORKSPACE_ID
    object_id = uuid.uuid4()
    async with database.sessions() as session:
        service = TraceService(session)
        context = await service.start_trace(
            StartTraceInput(
                event_type="object.creation",
                actor_id="service:test",
                actor_type="service",
                workspace_id=workspace_id,
                object_id=object_id,
                object_type="document",
                operation="document.create",
                metadata={"safe": ["json", 1, True]},
            )
        )
        await service.fail_trace(
            FailTraceInput(
                trace_id=context.trace_id,
                event_type="object.creation.failed",
                actor_id="service:test",
                actor_type="service",
                workspace_id=workspace_id,
                object_id=object_id,
                object_type="document",
                operation="document.create",
                error=TraceErrorInfo(
                    code="validation_failed",
                    message="Document validation failed",
                    details={"field": "sourceType"},
                ),
            )
        )
        await session.commit()

    response = await client.get(f"{api_prefix}/traces/{context.trace_id}")
    assert response.status_code == 200
    events = response.json()
    assert [event["status"] for event in events] == ["started", "failed"]
    assert events[0]["eventId"] != events[1]["eventId"]
    assert events[0]["workspaceId"] == str(workspace_id)
    assert events[0]["objectId"] == str(object_id)
    assert events[0]["metadata"] == {"safe": ["json", 1, True]}
    assert events[1]["error"] == {
        "code": "validation_failed",
        "message": "Document validation failed",
        "details": {"field": "sourceType"},
    }

    filtered = await client.get(
        f"{api_prefix}/trace-events",
        params={
            "workspaceId": str(workspace_id),
            "objectId": str(object_id),
            "eventType": "object.creation.failed",
            "status": "failed",
        },
    )
    assert filtered.status_code == 200
    assert [event["traceId"] for event in filtered.json()] == [str(context.trace_id)]


async def test_trace_read_api_rejects_invalid_filters(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    response = await client.get(f"{api_prefix}/trace-events", params={"limit": 501})
    assert response.status_code == 422
