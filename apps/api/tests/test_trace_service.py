from __future__ import annotations

import uuid
from datetime import UTC, datetime, tzinfo

import pytest
from pydantic import ValidationError

import opencanvas_api.services.trace as trace_module
from opencanvas_api.db.session import Database
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    FailTraceInput,
    RecordTraceEventInput,
    StartTraceInput,
    TraceErrorInfo,
    TraceQueryFilters,
    TraceService,
)


async def test_trace_lifecycle_persists_ordered_actor_workspace_and_object_metadata(
    database: Database,
) -> None:
    workspace_id = uuid.uuid4()
    object_id = uuid.uuid4()
    async with database.sessions() as session:
        service = TraceService(session)
        context = await service.start_trace(
            StartTraceInput(
                event_type="object.creation",
                actor_id="user-42",
                actor_type="user",
                workspace_id=workspace_id,
                object_id=object_id,
                object_type="note",
                operation="note.create",
                metadata={"request": {"source": "test"}},
            )
        )
        updated = await service.record_event(
            RecordTraceEventInput(
                trace_id=context.trace_id,
                event_type="object.updated",
                actor_id="user-42",
                actor_type="user",
                workspace_id=workspace_id,
                object_id=object_id,
                object_type="note",
                operation="note.update",
                status="succeeded",
                metadata={"version": 2},
            )
        )
        completed = await service.complete_trace(
            CompleteTraceInput(
                trace_id=context.trace_id,
                event_type="object.creation.completed",
                actor_id="user-42",
                actor_type="user",
                workspace_id=workspace_id,
                object_id=object_id,
                object_type="note",
                operation="note.create",
                metadata={"version": 2},
            )
        )
        await session.commit()

    assert len({context.start_event.event_id, updated.event_id, completed.event_id}) == 3
    async with database.sessions() as session:
        persisted = await TraceService(session).get_trace(context.trace_id)

    assert [event.status for event in persisted] == ["started", "succeeded", "succeeded"]
    assert [event.operation for event in persisted] == [
        "note.create",
        "note.update",
        "note.create",
    ]
    assert persisted[0].actor_id == "user-42"
    assert persisted[0].actor_type == "user"
    assert persisted[0].workspace_id == workspace_id
    assert persisted[0].object_id == object_id
    assert persisted[0].metadata_payload == {"request": {"source": "test"}}
    assert all(
        persisted[index].occurred_at <= persisted[index + 1].occurred_at
        for index in range(len(persisted) - 1)
    )


async def test_trace_lifecycle_remains_ordered_when_clock_values_repeat(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FrozenDateTime:
            return cls(2026, 7, 17, 12, 0, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(trace_module, "datetime", FrozenDateTime)

    trace_id = uuid.uuid4()
    async with database.sessions() as session:
        service = TraceService(session)
        for operation in ("note.create", "note.update", "note.complete"):
            await service.record_event(
                RecordTraceEventInput(
                    trace_id=trace_id,
                    event_type=operation,
                    actor_type="system",
                    operation=operation,
                    status="succeeded",
                )
            )
        await session.commit()

    async with database.sessions() as session:
        persisted = await TraceService(session).get_trace(trace_id)

    assert [event.operation for event in persisted] == [
        "note.create",
        "note.update",
        "note.complete",
    ]
    assert len({event.occurred_at for event in persisted}) == 3


async def test_parent_child_traces_and_filtered_queries(database: Database) -> None:
    workspace_id = uuid.uuid4()
    parent_object_id = uuid.uuid4()
    child_object_id = uuid.uuid4()
    async with database.sessions() as session:
        service = TraceService(session)
        parent = await service.start_trace(
            StartTraceInput(
                event_type="workflow.started",
                actor_type="service",
                workspace_id=workspace_id,
                object_id=parent_object_id,
                object_type="execution",
                operation="workflow.run",
            )
        )
        child = await service.start_trace(
            StartTraceInput(
                parent_trace_id=parent.trace_id,
                event_type="document.processing.started",
                actor_type="service",
                workspace_id=workspace_id,
                object_id=child_object_id,
                object_type="document",
                operation="document.process",
            )
        )
        await service.complete_trace(
            CompleteTraceInput(
                trace_id=child.trace_id,
                parent_trace_id=parent.trace_id,
                event_type="document.processing.completed",
                actor_type="service",
                workspace_id=workspace_id,
                object_id=child_object_id,
                object_type="document",
                operation="document.process",
            )
        )
        await session.commit()

        child_events = await service.query_trace_events(
            TraceQueryFilters(parent_trace_id=parent.trace_id)
        )
        workspace_events = await service.query_trace_events(
            TraceQueryFilters(workspace_id=workspace_id)
        )
        object_events = await service.query_trace_events(
            TraceQueryFilters(object_id=child_object_id)
        )
        typed_events = await service.query_trace_events(
            TraceQueryFilters(event_type="document.processing.completed")
        )

    assert len(child_events) == 2
    assert {event.trace_id for event in child_events} == {child.trace_id}
    assert len(workspace_events) == 3
    assert len(object_events) == 2
    assert [event.status for event in typed_events] == ["succeeded"]


async def test_failed_observed_operation_captures_structured_error(database: Database) -> None:
    async with database.sessions() as session:
        service = TraceService(session)
        context = await service.start_trace(
            StartTraceInput(
                event_type="relationship.creation",
                actor_type="system",
                operation="relationship.create",
                metadata={"attempt": 1},
            )
        )

        try:
            raise RuntimeError("storage unavailable")
        except RuntimeError as exc:
            failed = await service.fail_trace(
                FailTraceInput(
                    trace_id=context.trace_id,
                    event_type="relationship.creation.failed",
                    actor_type="system",
                    operation="relationship.create",
                    metadata={"retryable": True},
                    error=TraceErrorInfo(
                        code="storage_unavailable",
                        message=str(exc),
                        details={"backend": "test"},
                    ),
                )
            )
        await session.commit()

    assert failed.status == "failed"
    assert failed.error_payload == {
        "code": "storage_unavailable",
        "message": "storage unavailable",
        "details": {"backend": "test"},
    }
    async with database.sessions() as session:
        persisted = await TraceService(session).get_trace(context.trace_id)
    assert [event.status for event in persisted] == ["started", "failed"]


def test_trace_input_validation_rejects_malformed_and_unsafe_payloads() -> None:
    with pytest.raises(ValidationError, match="objectId and objectType"):
        StartTraceInput(
            event_type="object.created",
            operation="object.create",
            object_id=uuid.uuid4(),
        )
    with pytest.raises(ValidationError):
        StartTraceInput(
            event_type="object.created",
            operation="object.create",
            metadata={"unsafe": object()},  # type: ignore[dict-item]
        )
    with pytest.raises(ValidationError, match="structured error"):
        RecordTraceEventInput(
            trace_id=uuid.uuid4(),
            event_type="object.failed",
            operation="object.create",
            status="failed",
        )
