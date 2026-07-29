from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Base,
    Canvas,
    ControlledAgentExecution,
    DomainActivityEntry,
    DomainEventDeliveryAttempt,
    DomainEventOutbox,
    DomainEventProvenance,
    DomainEventRecord,
    User,
    Workspace,
    WorkspaceEventSequence,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.domain_events import (
    EVENT_TYPE_REGISTRY,
    CreateDomainEvent,
    DomainEventConflictError,
    DomainEventOutboxService,
    DomainEventService,
    DomainEventStorageError,
    DomainEventValidationError,
    OutboxOwnershipError,
)

NOW = datetime(2026, 7, 25, 16, 0, tzinfo=UTC)


async def _scope(database: Database) -> tuple[uuid.UUID, uuid.UUID]:
    canvas_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(Canvas(id=canvas_id, workspace_id=SYSTEM_WORKSPACE_ID, name="Events"))
        session.add(
            ControlledAgentExecution(
                id=execution_id,
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                schema_version="controlled-agent-v1",
                role="drafting_assistant",
                context_snapshot_id=uuid.uuid4(),
                context_digest="a" * 64,
                plan_id=uuid.uuid4(),
                plan_digest="b" * 64,
                grant_id=uuid.uuid4(),
                created_at=NOW,
                deadline_at=NOW + timedelta(minutes=15),
                max_attempts=3,
                attempt_count=0,
                lease_generation=0,
            )
        )
        await session.commit()
    return canvas_id, execution_id


def _command(
    event_type: str,
    *,
    canvas_id: uuid.UUID,
    execution_id: uuid.UUID,
    source_identity: str | None = None,
    trace_id: uuid.UUID | None = None,
    max_attempts: int = 3,
) -> CreateDomainEvent:
    spec = EVENT_TYPE_REGISTRY[event_type]  # type: ignore[index]
    payloads = {
        "graph_relationship": {
            "relationshipType": "references",
            "state": "active",
            "graphRevision": 1,
        },
        "canonical_resource": {
            "objectType": "note",
            "version": 1,
            "lifecycleState": "active",
        },
        "controlled_execution": {"status": "running"},
        "controlled_effect": {
            "action": "note.create",
            "noteId": str(uuid.uuid4()),
            "resultingRevision": 0,
        },
        "controlled_rollback": {
            "action": "note.create.rollback",
            "noteId": str(uuid.uuid4()),
        },
    }
    needs_execution = spec.execution_required
    return CreateDomainEvent(
        event_type=event_type,
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id if spec.canvas_required else None,
        subject_id=execution_id if needs_execution else uuid.uuid4(),
        actor_user_id=SYSTEM_USER_ID,
        execution_id=execution_id if needs_execution else None,
        source_identity=source_identity or f"{event_type}:{uuid.uuid4()}",
        trace_id=trace_id or uuid.uuid4(),
        payload=payloads.get(spec.subject_kind, {}),
        origin_type="controlled_execution" if needs_execution else "authenticated_user",
        graph_revision=1 if spec.subject_kind == "graph_relationship" else None,
        occurred_at=NOW,
        max_attempts=max_attempts,
    )


@pytest.mark.anyio
async def test_closed_existing_registry_persists_event_provenance_and_outbox(
    database: Database,
) -> None:
    canvas_id, execution_id = await _scope(database)
    externally_scoped_subjects = {
        "workspace_invitation",
        "workspace_membership",
        "collaboration_resource",
        "resource_share",
        "ownership_transfer",
        "authority_fence",
        "comment_thread",
        "comment",
        "ingestion_request",
        "index_revision",
        "index_publication",
        "durable_job",
    }
    existing_types = [
        name
        for name, spec in EVENT_TYPE_REGISTRY.items()
        if not spec.reserved and spec.subject_kind not in externally_scoped_subjects
    ]
    async with database.sessions() as session:
        service = DomainEventService(session)
        recorded = [
            await service.record(_command(name, canvas_id=canvas_id, execution_id=execution_id))
            for name in existing_types
        ]
        await session.commit()
        assert [item.event.sequence for item in recorded] == list(range(1, len(existing_types) + 1))
        assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) == len(
            existing_types
        )
        assert await session.scalar(select(func.count()).select_from(DomainEventProvenance)) == len(
            existing_types
        )
        assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) == len(
            existing_types
        )
        sequence = await session.get(WorkspaceEventSequence, SYSTEM_WORKSPACE_ID)
        assert sequence is not None
        assert sequence.last_sequence == len(existing_types)
        assert all(item.event.actor_user_id == SYSTEM_USER_ID for item in recorded)
        assert all(item.outbox.delivery_state == "pending" for item in recorded)


@pytest.mark.anyio
async def test_reserved_future_contracts_and_unknown_types_fail_closed(
    database: Database,
) -> None:
    canvas_id, execution_id = await _scope(database)
    async with database.sessions() as session:
        service = DomainEventService(session)
        for name, spec in EVENT_TYPE_REGISTRY.items():
            if spec.reserved:
                with pytest.raises(DomainEventValidationError):
                    await service.record(
                        _command(name, canvas_id=canvas_id, execution_id=execution_id)
                    )
        unknown = _command(
            "graph.relationship.created",
            canvas_id=canvas_id,
            execution_id=execution_id,
        )
        with pytest.raises(DomainEventValidationError):
            await service.record(replace(unknown, event_type="unregistered.free_text"))
        assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) == 0


@pytest.mark.anyio
async def test_exact_duplicate_replays_and_conflicting_reuse_fails_closed(
    database: Database,
) -> None:
    canvas_id, execution_id = await _scope(database)
    command = _command(
        "graph.relationship.created",
        canvas_id=canvas_id,
        execution_id=execution_id,
        source_identity="graph-create-1",
    )
    async with database.sessions() as session:
        service = DomainEventService(session)
        first = await service.record(command)
        duplicate = await service.record(replace(command, trace_id=uuid.uuid4()))
        assert duplicate.duplicate is True
        assert duplicate.event.event_id == first.event.event_id
        conflicting = replace(
            command,
            payload={
                "relationshipType": "related_to",
                "state": "active",
                "graphRevision": 1,
            },
        )
        with pytest.raises(DomainEventConflictError):
            await service.record(conflicting)
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("failure_point", ["event", "provenance", "outbox"])
async def test_injected_creation_failures_leave_no_partial_evidence(
    database: Database,
    failure_point: str,
) -> None:
    canvas_id, execution_id = await _scope(database)

    def fail() -> None:
        raise RuntimeError("injected")

    hooks = {
        "after_event": fail if failure_point == "event" else None,
        "after_provenance": fail if failure_point == "provenance" else None,
        "after_outbox": fail if failure_point == "outbox" else None,
    }
    async with database.sessions() as session:
        service = DomainEventService(session, **hooks)
        with pytest.raises(RuntimeError, match="injected"):
            await service.record(
                _command(
                    "graph.relationship.created",
                    canvas_id=canvas_id,
                    execution_id=execution_id,
                )
            )
        assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(DomainEventProvenance)) == 0
        assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) == 0
        assert await session.get(WorkspaceEventSequence, SYSTEM_WORKSPACE_ID) is None


@pytest.mark.anyio
async def test_outbox_claim_fencing_retry_completion_and_projection_are_bounded(
    database: Database,
) -> None:
    canvas_id, execution_id = await _scope(database)
    async with database.sessions() as session:
        recorded = await DomainEventService(session).record(
            _command(
                "graph.relationship.created",
                canvas_id=canvas_id,
                execution_id=execution_id,
                max_attempts=3,
            )
        )
        outbox = DomainEventOutboxService(session)
        first = await outbox.claim_one(owner_id="dispatcher-a", now=NOW, lease_seconds=30)
        assert first is not None
        assert await outbox.claim_one(owner_id="dispatcher-b", now=NOW) is None
        second = await outbox.claim_one(
            owner_id="dispatcher-b",
            now=NOW + timedelta(seconds=31),
            lease_seconds=30,
        )
        assert second is not None
        with pytest.raises(OutboxOwnershipError):
            await outbox.complete(first, now=NOW + timedelta(seconds=31))
        state = await outbox.fail(
            second,
            failure_classification="consumer_retryable",
            retryable=True,
            now=NOW + timedelta(seconds=31),
        )
        assert state == "retry_wait"
        third = await outbox.claim_one(
            owner_id="dispatcher-c",
            now=NOW + timedelta(seconds=33),
        )
        assert third is not None
        assert await outbox.project_activity(third) is True
        assert await outbox.project_activity(third) is False
        await outbox.complete(third, now=NOW + timedelta(seconds=33))
        assert (
            await outbox.claim_one(
                owner_id="dispatcher-d",
                now=NOW + timedelta(minutes=10),
            )
            is None
        )
        await session.commit()
        persisted = await session.get(DomainEventOutbox, recorded.outbox.outbox_id)
        assert persisted is not None
        assert persisted.delivery_state == "delivered"
        assert persisted.attempt_count == 3
        assert (
            await session.scalar(select(func.count()).select_from(DomainEventDeliveryAttempt)) == 2
        )
        assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 1


@pytest.mark.anyio
async def test_exhausted_or_unknown_failure_is_terminal_without_false_success(
    database: Database,
) -> None:
    canvas_id, execution_id = await _scope(database)
    async with database.sessions() as session:
        recorded = await DomainEventService(session).record(
            _command(
                "graph.relationship.deactivated",
                canvas_id=canvas_id,
                execution_id=execution_id,
                max_attempts=1,
            )
        )
        outbox = DomainEventOutboxService(session)
        claim = await outbox.claim_one(owner_id="dispatcher", now=NOW)
        assert claim is not None
        state = await outbox.fail(
            claim,
            failure_classification="provider_secret_failure",
            retryable=True,
            now=NOW,
        )
        assert state == "terminal_failure"
        persisted = await session.get(DomainEventOutbox, recorded.outbox.outbox_id)
        assert persisted is not None
        assert persisted.failure_classification == "unsafe_failure"
        assert persisted.completed_at is None
        assert persisted.terminal_at == NOW


@pytest.mark.anyio
async def test_activity_reads_are_deterministic_bounded_and_safe(
    database: Database,
) -> None:
    canvas_id, execution_id = await _scope(database)
    async with database.sessions() as session:
        service = DomainEventService(session)
        first = await service.record(
            _command(
                "graph.relationship.created",
                canvas_id=canvas_id,
                execution_id=execution_id,
                source_identity="one",
            )
        )
        second = await service.record(
            _command(
                "graph.relationship.deactivated",
                canvas_id=canvas_id,
                execution_id=execution_id,
                source_identity="two",
            )
        )
        rows = await service.list_activity(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            limit=1,
            offset=0,
        )
        assert [row.event.event_id for row in rows] == [second.event.event_id]
        assert rows[0].status == "pending_delivery"
        rows = await service.list_activity(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            subject_id=first.event.subject_id,
            limit=10,
            offset=0,
        )
        assert [row.event.event_id for row in rows] == [first.event.event_id]
        with pytest.raises(DomainEventValidationError):
            await service.list_activity(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                limit=101,
                offset=0,
            )


@pytest.mark.anyio
async def test_event_and_projection_are_append_only(database: Database) -> None:
    canvas_id, execution_id = await _scope(database)
    async with database.sessions() as session:
        recorded = await DomainEventService(session).record(
            _command(
                "graph.relationship.created",
                canvas_id=canvas_id,
                execution_id=execution_id,
            )
        )
        event_id = recorded.event.event_id
        await session.commit()
        recorded.event.event_type = "graph.relationship.deactivated"
        with pytest.raises(ValueError, match="append-only"):
            await session.flush()
        await session.rollback()
        event = await session.get(DomainEventRecord, event_id)
        assert event is not None
        await session.delete(event)
        with pytest.raises(ValueError, match="append-only"):
            await session.flush()


@pytest.mark.anyio
async def test_outbox_identity_is_immutable_but_lifecycle_is_mutable(
    database: Database,
) -> None:
    canvas_id, execution_id = await _scope(database)
    async with database.sessions() as session:
        recorded = await DomainEventService(session).record(
            _command(
                "graph.relationship.created",
                canvas_id=canvas_id,
                execution_id=execution_id,
            )
        )
        outbox_id = recorded.outbox.outbox_id
        await session.commit()
        recorded.outbox.max_attempts = 9
        with pytest.raises(ValueError, match="identity and scope"):
            await session.flush()
        await session.rollback()
        outbox = await session.get(DomainEventOutbox, outbox_id)
        assert outbox is not None
        outbox.failure_classification = "consumer_retryable"
        await session.flush()


async def _file_database(path: Path) -> Database:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.sessions() as session:
        session.add(
            User(
                id=SYSTEM_USER_ID,
                email="event-concurrency@mobius.invalid",
                email_normalized="event-concurrency@mobius.invalid",
                password_hash="test-only",
                display_name="Event concurrency",
                email_verified=True,
            )
        )
        session.add(
            Workspace(
                id=SYSTEM_WORKSPACE_ID,
                owner_id=SYSTEM_USER_ID,
                name="Event concurrency",
            )
        )
        await session.commit()
    await _scope(database)
    return database


@pytest.mark.anyio
async def test_competing_exact_event_creation_persists_one_event(
    tmp_path: Path,
) -> None:
    database = await _file_database(tmp_path / "event-concurrency.db")
    canvas_id: uuid.UUID
    execution_id: uuid.UUID
    async with database.sessions() as session:
        canvas_id = await session.scalar(select(Canvas.id))
        execution_id = await session.scalar(select(ControlledAgentExecution.id))
        assert canvas_id is not None and execution_id is not None
    command = _command(
        "graph.relationship.created",
        canvas_id=canvas_id,
        execution_id=execution_id,
        source_identity="competing-exact-event",
    )

    async def create() -> tuple[uuid.UUID, bool]:
        async with database.sessions() as session:
            result = await DomainEventService(session).record(command)
            await session.commit()
            return result.event.event_id, result.duplicate

    try:
        results = await asyncio.gather(create(), create(), return_exceptions=True)
        successful = [result for result in results if isinstance(result, tuple)]
        rejected = [result for result in results if isinstance(result, BaseException)]
        assert len(successful) >= 1
        assert len({result[0] for result in successful}) == 1
        assert all(isinstance(result, DomainEventStorageError) for result in rejected)
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) == 1
            assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) == 1
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_competing_outbox_claims_produce_one_owner(tmp_path: Path) -> None:
    database = await _file_database(tmp_path / "claim-concurrency.db")
    async with database.sessions() as session:
        canvas_id = await session.scalar(select(Canvas.id))
        execution_id = await session.scalar(select(ControlledAgentExecution.id))
        assert canvas_id is not None and execution_id is not None
        await DomainEventService(session).record(
            _command(
                "graph.relationship.created",
                canvas_id=canvas_id,
                execution_id=execution_id,
                source_identity="competing-claim",
            )
        )
        await session.commit()

    async def claim(owner: str) -> str | None:
        async with database.sessions() as session:
            result = await DomainEventOutboxService(session).claim_one(
                owner_id=owner,
                now=NOW,
            )
            await session.commit()
            return result.owner_id if result is not None else None

    try:
        owners = [owner for owner in await asyncio.gather(claim("a"), claim("b")) if owner]
        assert len(owners) == 1
    finally:
        await database.dispose()
