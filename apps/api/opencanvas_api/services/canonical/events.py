from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, TypeVar, cast

from pydantic import JsonValue


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    workspace_id: uuid.UUID
    actor_id: str | None = None
    trace_id: uuid.UUID | None = None
    object_id: uuid.UUID | None = None
    object_type: str | None = None
    object_version: int | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceCreated(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceUpdated(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceTransitioned(DomainEvent):
    previous_state: str
    current_state: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceDeleted(DomainEvent):
    previous_state: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalObjectCreated(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalObjectUpdated(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalObjectTransitioned(DomainEvent):
    previous_state: str
    current_state: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalObjectDeleted(DomainEvent):
    previous_state: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalRelationshipCreated(DomainEvent):
    relationship_id: uuid.UUID
    relationship_type: str
    source_object_id: uuid.UUID
    target_object_id: uuid.UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalRelationshipDeleted(DomainEvent):
    relationship_id: uuid.UUID
    relationship_type: str
    source_object_id: uuid.UUID
    target_object_id: uuid.UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalRelationshipRemoved(CanonicalRelationshipDeleted):
    """Explicit relationship-removal event; retained deletion class is compatibility vocabulary."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStarted(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionCompleted(DomainEvent):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionFailed(DomainEvent):
    error_code: str
    error_message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TraceEventRecorded(DomainEvent):
    """Marker event emitted after persistent Trace evidence is recorded."""

    trace_event_id: uuid.UUID


DomainEventHandler = Callable[[DomainEvent], Awaitable[None]]
EventT = TypeVar("EventT", bound=DomainEvent)


@dataclass(frozen=True, slots=True)
class SubscriberFailure:
    subscriber_name: str
    error: Exception


@dataclass(frozen=True, slots=True)
class PublishResult:
    delivered: int
    failures: tuple[SubscriberFailure, ...] = ()
    recursion_suppressed: bool = False


class DomainEventPublisher(Protocol):
    async def publish(self, event: DomainEvent) -> PublishResult: ...


_publishing_trace_marker: ContextVar[bool] = ContextVar(
    "canonical_publishing_trace_marker", default=False
)


class InMemoryDomainEventBus:
    """Replaceable process-local event bus with isolated subscriber failures."""

    def __init__(self) -> None:
        self._subscribers: dict[type[DomainEvent], list[DomainEventHandler]] = defaultdict(list)

    def subscribe(
        self,
        event_type: type[EventT],
        subscriber: Callable[[EventT], Awaitable[None]],
    ) -> Callable[[], None]:
        generic_subscriber = cast(DomainEventHandler, subscriber)
        self._subscribers[event_type].append(generic_subscriber)

        def unsubscribe() -> None:
            subscribers = self._subscribers.get(event_type)
            if subscribers is not None and generic_subscriber in subscribers:
                subscribers.remove(generic_subscriber)

        return unsubscribe

    async def publish(self, event: DomainEvent) -> PublishResult:
        is_trace_marker = isinstance(event, TraceEventRecorded)
        if is_trace_marker and _publishing_trace_marker.get():
            return PublishResult(delivered=0, recursion_suppressed=True)

        token = _publishing_trace_marker.set(True) if is_trace_marker else None
        try:
            subscribers = [
                subscriber
                for subscribed_type, handlers in self._subscribers.items()
                if isinstance(event, subscribed_type)
                for subscriber in handlers
            ]
            failures: list[SubscriberFailure] = []
            delivered = 0
            for subscriber in tuple(subscribers):
                try:
                    await subscriber(event)
                    delivered += 1
                except Exception as exc:  # Subscribers must not fail the domain mutation.
                    failures.append(
                        SubscriberFailure(
                            subscriber_name=_subscriber_name(subscriber),
                            error=exc,
                        )
                    )
            return PublishResult(delivered=delivered, failures=tuple(failures))
        finally:
            if token is not None:
                _publishing_trace_marker.reset(token)


def _subscriber_name(subscriber: DomainEventHandler) -> str:
    return getattr(subscriber, "__qualname__", type(subscriber).__qualname__)
