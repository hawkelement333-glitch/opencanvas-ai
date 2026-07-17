from __future__ import annotations

import uuid

import pytest

from opencanvas_api.services.canonical.events import (
    CanonicalObjectCreated,
    DomainEvent,
    InMemoryDomainEventBus,
    TraceEventRecorded,
)
from opencanvas_api.services.canonical.lifecycle import (
    InvalidLifecycleTransition,
    LifecycleState,
    allowed_transitions,
    ensure_transition,
)


def test_lifecycle_has_exact_non_destructive_transition_vocabulary() -> None:
    assert allowed_transitions("created") == {
        LifecycleState.ACTIVE,
        LifecycleState.DELETED,
    }
    assert allowed_transitions("active") == {
        LifecycleState.ARCHIVED,
        LifecycleState.DELETED,
    }
    assert allowed_transitions("archived") == {
        LifecycleState.ACTIVE,
        LifecycleState.DELETED,
    }
    assert allowed_transitions("deleted") == set()
    assert ensure_transition("created", "active") is LifecycleState.ACTIVE

    with pytest.raises(InvalidLifecycleTransition):
        ensure_transition("created", "archived")
    with pytest.raises(InvalidLifecycleTransition):
        ensure_transition("deleted", "active")


async def test_event_bus_isolates_subscriber_failures_and_can_unsubscribe() -> None:
    bus = InMemoryDomainEventBus()
    delivered: list[uuid.UUID] = []

    async def failing(_: DomainEvent) -> None:
        raise RuntimeError("subscriber unavailable")

    async def healthy(event: CanonicalObjectCreated) -> None:
        delivered.append(event.event_id)

    bus.subscribe(DomainEvent, failing)
    unsubscribe = bus.subscribe(CanonicalObjectCreated, healthy)
    event = CanonicalObjectCreated(
        workspace_id=uuid.uuid4(),
        object_id=uuid.uuid4(),
        object_type="note",
        object_version=1,
    )

    first = await bus.publish(event)
    unsubscribe()
    second = await bus.publish(event)

    assert first.delivered == 1
    assert len(first.failures) == 1
    assert first.failures[0].subscriber_name.endswith("failing")
    assert delivered == [event.event_id]
    assert second.delivered == 0
    assert len(second.failures) == 1


async def test_trace_event_marker_stops_recursive_trace_publication() -> None:
    bus = InMemoryDomainEventBus()
    nested_results: list[bool] = []

    async def trace_subscriber(event: TraceEventRecorded) -> None:
        nested = await bus.publish(event)
        nested_results.append(nested.recursion_suppressed)

    bus.subscribe(TraceEventRecorded, trace_subscriber)
    result = await bus.publish(
        TraceEventRecorded(
            workspace_id=uuid.uuid4(),
            trace_id=uuid.uuid4(),
            trace_event_id=uuid.uuid4(),
        )
    )

    assert result.delivered == 1
    assert nested_results == [True]
