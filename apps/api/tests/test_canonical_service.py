from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, NoReturn

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    SYSTEM_WORKSPACE_ID,
    CanonicalExecution,
    CanonicalRelationship,
    Canvas,
    Document,
    TraceEvent,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.canonical.events import (
    CanonicalRelationshipRemoved,
    DomainEvent,
    ExecutionCompleted,
    ExecutionStarted,
    InMemoryDomainEventBus,
    WorkspaceCreated,
)
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalNotFoundError,
    CanonicalStorageError,
    CanonicalValidationError,
    LifecycleState,
)
from opencanvas_api.services.canonical.repository import CanonicalRepository
from opencanvas_api.services.canonical.service import (
    CanonicalService,
    CreateObjectInput,
    CreateRelationshipInput,
    CreateWorkspaceInput,
    RemoveRelationshipInput,
    TransitionObjectInput,
    TransitionWorkspaceInput,
    UpdateObjectInput,
)
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    TracePersistenceError,
    TraceService,
)


async def _create_workspace(service: CanonicalService, name: str = "Knowledge") -> uuid.UUID:
    workspace = await service.create_workspace(CreateWorkspaceInput(name=name, actor_id="user-1"))
    return workspace.id


async def _create_note(service: CanonicalService, workspace_id: uuid.UUID, title: str) -> Any:
    return await service.create_object(
        CreateObjectInput(
            workspace_id=workspace_id,
            object_type="note",
            payload={"title": title, "content": "Canonical content"},
            metadata={"kind": "test"},
            actor_id="user-1",
        )
    )


async def test_service_versions_metadata_events_and_success_trace_are_coherent(
    database: Database,
) -> None:
    event_bus = InMemoryDomainEventBus()
    domain_events: list[DomainEvent] = []

    async def capture(event: DomainEvent) -> None:
        domain_events.append(event)

    event_bus.subscribe(DomainEvent, capture)
    async with database.sessions() as session:
        service = CanonicalService(session, event_bus=event_bus)
        workspace_id = await _create_workspace(service)
        created = await _create_note(service, workspace_id, "First title")
        updated = await service.update_object(
            UpdateObjectInput(
                workspace_id=workspace_id,
                object_id=created.object.id,
                expected_version=1,
                payload={"title": "Updated title"},
                metadata={"kind": "updated"},
                actor_id="user-1",
            )
        )
        await session.commit()

    assert updated.object.version == 2
    assert updated.object.metadata_payload == {"kind": "updated"}
    assert updated.detail.title == "Updated title"  # type: ignore[union-attr]
    workspace_event = next(event for event in domain_events if isinstance(event, WorkspaceCreated))
    assert workspace_event.trace_id is not None

    async with database.sessions() as session:
        trace_events = (
            await session.scalars(
                select(TraceEvent)
                .where(TraceEvent.operation == "canonical.object.update")
                .order_by(TraceEvent.occurred_at, TraceEvent.event_id)
            )
        ).all()
    assert [event.status for event in trace_events] == ["started", "succeeded"]
    assert trace_events[-1].metadata_payload == {"previousVersion": 1, "newVersion": 2}


async def test_validation_and_storage_failures_emit_durable_failed_traces(
    database: Database,
) -> None:
    async with database.sessions() as session:
        service = CanonicalService(session)
        workspace_id = await _create_workspace(service)
        await session.commit()

        with pytest.raises(CanonicalValidationError):
            await service.create_object(
                CreateObjectInput(
                    workspace_id=workspace_id,
                    object_type="note",
                    payload={"title": "Valid", "content": "", "unexpected": True},
                )
            )
        # The service flushes failed evidence; callers deliberately commit it after catching.
        await session.commit()

    async with database.sessions() as session:
        validation_trace = (
            await session.scalars(
                select(TraceEvent)
                .where(TraceEvent.operation == "canonical.object.create")
                .order_by(TraceEvent.occurred_at, TraceEvent.event_id)
            )
        ).all()
    assert [event.status for event in validation_trace] == ["started", "failed"]
    assert validation_trace[-1].error_payload is not None
    assert validation_trace[-1].error_payload["code"] == "canonical_validation_failed"

    class FailingRepository(CanonicalRepository):
        async def create_object(self, **_: Any) -> NoReturn:  # type: ignore[override]
            raise CanonicalStorageError("Injected storage failure.")

    async with database.sessions() as session:
        service = CanonicalService(session, repository=FailingRepository(session))
        with pytest.raises(CanonicalStorageError, match="Injected"):
            await service.create_object(
                CreateObjectInput(
                    workspace_id=workspace_id,
                    object_type="note",
                    payload={"title": "Storage", "content": "failure"},
                )
            )
        await session.commit()

    async with database.sessions() as session:
        storage_failure = await session.scalar(
            select(TraceEvent)
            .where(
                TraceEvent.operation == "canonical.object.create",
                TraceEvent.status == "failed",
                TraceEvent.error_payload["code"].as_string() == "canonical_storage_failed",
            )
            .order_by(TraceEvent.occurred_at.desc())
        )
    assert storage_failure is not None


async def test_update_and_transition_lookup_failures_emit_durable_failed_traces(
    database: Database,
) -> None:
    missing_id = uuid.uuid4()
    async with database.sessions() as session:
        service = CanonicalService(session)
        workspace_id = await _create_workspace(service)
        await session.commit()

        with pytest.raises(CanonicalNotFoundError):
            await service.update_object(
                UpdateObjectInput(
                    workspace_id=workspace_id,
                    object_id=missing_id,
                    expected_version=1,
                    metadata={"missing": True},
                )
            )
        with pytest.raises(CanonicalNotFoundError):
            await service.transition_object(
                TransitionObjectInput(
                    workspace_id=workspace_id,
                    object_id=missing_id,
                    expected_version=1,
                    target_state=LifecycleState.ACTIVE,
                )
            )
        await session.commit()

    async with database.sessions() as session:
        trace_events = (
            await session.scalars(
                select(TraceEvent)
                .where(
                    TraceEvent.object_id == missing_id,
                    TraceEvent.operation.in_(
                        ("canonical.object.update", "canonical.object.transition")
                    ),
                )
                .order_by(TraceEvent.operation, TraceEvent.occurred_at, TraceEvent.event_id)
            )
        ).all()

    assert [(event.operation, event.status, event.object_type) for event in trace_events] == [
        ("canonical.object.transition", "started", "canonical_object"),
        ("canonical.object.transition", "failed", "canonical_object"),
        ("canonical.object.update", "started", "canonical_object"),
        ("canonical.object.update", "failed", "canonical_object"),
    ]


async def test_trace_completion_failure_rolls_back_domain_mutation_before_failure_evidence(
    database: Database,
) -> None:
    class CompletionFailingTraceService(TraceService):
        async def complete_trace(self, input_data: CompleteTraceInput) -> NoReturn:
            del input_data
            raise TracePersistenceError("Injected completion failure")

    async with database.sessions() as session:
        service = CanonicalService(
            session,
            trace_service=CompletionFailingTraceService(session),
        )
        with pytest.raises(CanonicalStorageError, match="completion"):
            await service.create_workspace(CreateWorkspaceInput(name="Must roll back"))
        await session.commit()

    async with database.sessions() as session:
        workspace_count = await session.scalar(
            select(func.count()).select_from(Workspace).where(Workspace.id != SYSTEM_WORKSPACE_ID)
        )
        trace_events = (
            await session.scalars(
                select(TraceEvent)
                .where(TraceEvent.operation == "canonical.workspace.create")
                .order_by(TraceEvent.occurred_at, TraceEvent.event_id)
            )
        ).all()
    assert workspace_count == 0
    assert [event.status for event in trace_events] == ["started", "failed"]


async def test_relationship_removal_is_first_class_and_endpoint_delete_is_safe(
    database: Database,
) -> None:
    event_bus = InMemoryDomainEventBus()
    removed_events: list[CanonicalRelationshipRemoved] = []

    async def capture_removed(event: CanonicalRelationshipRemoved) -> None:
        removed_events.append(event)

    event_bus.subscribe(CanonicalRelationshipRemoved, capture_removed)
    async with database.sessions() as session:
        service = CanonicalService(session, event_bus=event_bus)
        workspace_id = await _create_workspace(service)
        source = await _create_note(service, workspace_id, "Source")
        target = await _create_note(service, workspace_id, "Target")
        relationship = await service.create_relationship(
            CreateRelationshipInput(
                workspace_id=workspace_id,
                relationship_type="references",
                source_object_id=source.object.id,
                target_object_id=target.object.id,
                actor_id=str(uuid.uuid4()),
            )
        )
        assert isinstance(relationship.detail, CanonicalRelationship)
        assert relationship.detail.trace_id is not None

        with pytest.raises(CanonicalConflictError, match="Remove active relationships"):
            await service.transition_object(
                TransitionObjectInput(
                    workspace_id=workspace_id,
                    object_id=source.object.id,
                    expected_version=1,
                    target_state=LifecycleState.DELETED,
                )
            )
        await session.commit()

        removed = await service.remove_relationship(
            RemoveRelationshipInput(
                workspace_id=workspace_id,
                relationship_id=relationship.object.id,
                expected_version=1,
            )
        )
        assert removed.object.lifecycle_state == "deleted"
        assert removed.object.version == 2
        with pytest.raises(CanonicalConflictError, match="already exists"):
            await service.create_relationship(
                CreateRelationshipInput(
                    workspace_id=workspace_id,
                    relationship_type="references",
                    source_object_id=source.object.id,
                    target_object_id=target.object.id,
                )
            )
        await session.commit()

        deleted_source = await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=source.object.id,
                expected_version=1,
                target_state=LifecycleState.DELETED,
            )
        )
        await session.commit()

    assert deleted_source.object.lifecycle_state == "deleted"
    assert len(removed_events) == 1


async def test_execution_updates_publish_started_completed_events_and_revalidate_fields(
    database: Database,
) -> None:
    event_bus = InMemoryDomainEventBus()
    execution_events: list[DomainEvent] = []

    async def capture(event: DomainEvent) -> None:
        if isinstance(event, (ExecutionStarted, ExecutionCompleted)):
            execution_events.append(event)

    event_bus.subscribe(DomainEvent, capture)
    started_at = datetime.now(UTC)
    completed_at = datetime.now(UTC)
    async with database.sessions() as session:
        service = CanonicalService(session, event_bus=event_bus)
        workspace_id = await _create_workspace(service)
        execution = await service.create_object(
            CreateObjectInput(
                workspace_id=workspace_id,
                object_type="execution",
                payload={
                    "execution_type": "retrieval",
                    "status": "pending",
                    "inputs_metadata": {"query": "facts"},
                },
            )
        )
        running = await service.update_object(
            UpdateObjectInput(
                workspace_id=workspace_id,
                object_id=execution.object.id,
                expected_version=1,
                payload={"status": "running", "started_at": started_at.isoformat()},
            )
        )
        execution_id = execution.object.id
        await session.commit()

    # SQLite round-trips timestamps without timezone information. A later request still compares
    # that persisted start against an offset-aware completion timestamp safely in UTC.
    async with database.sessions() as session:
        service = CanonicalService(session, event_bus=event_bus)
        completed = await service.update_object(
            UpdateObjectInput(
                workspace_id=workspace_id,
                object_id=execution_id,
                expected_version=2,
                payload={"status": "succeeded", "completed_at": completed_at.isoformat()},
            )
        )
        await session.commit()

    assert isinstance(running.detail, CanonicalExecution)
    assert isinstance(completed.detail, CanonicalExecution)
    assert completed.detail.status == "succeeded"
    assert [type(event) for event in execution_events] == [ExecutionStarted, ExecutionCompleted]

    with pytest.raises(ValidationError):
        UpdateObjectInput(
            workspace_id=workspace_id,
            object_id=execution_id,
            expected_version=3,
            payload={},
        )
    with pytest.raises(ValidationError):
        CreateWorkspaceInput(name="Valid", actor_id="   ")


async def test_lifecycle_trace_metadata_deleted_workspace_boundary_and_chunk_guard(
    database: Database,
) -> None:
    async with database.sessions() as session:
        service = CanonicalService(session)
        workspace_id = await _create_workspace(service)
        note = await _create_note(service, workspace_id, "Lifecycle")
        active = await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=note.object.id,
                expected_version=1,
                target_state=LifecycleState.ACTIVE,
            )
        )
        archived = await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=note.object.id,
                expected_version=active.object.version,
                target_state=LifecycleState.ARCHIVED,
            )
        )
        with pytest.raises(CanonicalConflictError, match="reactivated"):
            await service.update_object(
                UpdateObjectInput(
                    workspace_id=workspace_id,
                    object_id=note.object.id,
                    expected_version=archived.object.version,
                    metadata={"forbidden": True},
                )
            )
        await session.commit()
        reactivated = await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=note.object.id,
                expected_version=archived.object.version,
                target_state=LifecycleState.ACTIVE,
            )
        )
        assert reactivated.object.version == 4

        document = await service.create_object(
            CreateObjectInput(
                workspace_id=workspace_id,
                object_type="document",
                payload={"display_name": "Parent", "source_type": "test"},
            )
        )
        chunk = await service.create_object(
            CreateObjectInput(
                workspace_id=workspace_id,
                object_type="chunk",
                payload={
                    "document_object_id": str(document.object.id),
                    "ordered_position": 0,
                    "content": "Child chunk",
                },
            )
        )
        with pytest.raises(CanonicalConflictError, match="live chunks"):
            await service.transition_object(
                TransitionObjectInput(
                    workspace_id=workspace_id,
                    object_id=document.object.id,
                    expected_version=1,
                    target_state=LifecycleState.DELETED,
                )
            )
        await session.commit()
        await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=chunk.object.id,
                expected_version=1,
                target_state=LifecycleState.DELETED,
            )
        )
        await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=document.object.id,
                expected_version=1,
                target_state=LifecycleState.DELETED,
            )
        )
        deleted_workspace = await service.transition_workspace(
            TransitionWorkspaceInput(
                workspace_id=workspace_id,
                expected_version=1,
                target_state=LifecycleState.DELETED,
            )
        )
        await session.commit()

    assert deleted_workspace.lifecycle_state == "deleted"
    async with database.sessions() as session:
        service = CanonicalService(session)
        with pytest.raises(CanonicalNotFoundError, match="Workspace not found"):
            await service.get_object(workspace_id, note.object.id)
        audit_note = await service.get_object(workspace_id, note.object.id, include_deleted=True)
        assert audit_note.object.id == note.object.id
        transition_success = await session.scalar(
            select(TraceEvent)
            .where(
                TraceEvent.operation == "canonical.object.transition",
                TraceEvent.status == "succeeded",
                TraceEvent.object_id == note.object.id,
            )
            .order_by(TraceEvent.occurred_at.desc())
        )
    assert transition_success is not None
    assert transition_success.object_type == "note"
    assert transition_success.metadata_payload == {
        "previousVersion": 3,
        "newVersion": 4,
        "previousState": "archived",
        "currentState": "active",
    }


async def test_legacy_document_reference_must_match_workspace_canvas(
    database: Database,
) -> None:
    async with database.sessions() as session:
        first_canvas = Canvas(name="First legacy canvas")
        second_canvas = Canvas(name="Second legacy canvas")
        session.add_all([first_canvas, second_canvas])
        await session.flush()
        foreign_document = Document(
            canvas_id=second_canvas.id,
            file_name="foreign.txt",
            file_type="txt",
            media_type="text/plain",
            file_size_bytes=12,
            content_sha256="a" * 64,
            status="ready",
            processing_stage="ready",
            chunk_count=1,
        )
        session.add(foreign_document)
        service = CanonicalService(session)
        workspace_id = await _create_workspace(service)
        workspace = await service.get_workspace(workspace_id)
        workspace.legacy_canvas_id = first_canvas.id
        await session.flush()

        with pytest.raises(CanonicalValidationError, match="legacy canvas"):
            await service.create_object(
                CreateObjectInput(
                    workspace_id=workspace_id,
                    object_type="document",
                    payload={
                        "display_name": "Foreign",
                        "source_type": "legacy",
                        "legacy_document_id": str(foreign_document.id),
                    },
                )
            )
        await session.commit()
