from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from sqlalchemy import Select, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import TraceEvent

ActorType = Literal["user", "system", "service"]
TraceStatus = Literal["started", "succeeded", "failed"]


class TraceInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TraceErrorInfo(TraceInputModel):
    code: str | None = Field(default=None, min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=4_000)
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("code", "message")
    @classmethod
    def trim_error_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("trace error text must not be blank")
        return trimmed


class TraceEventBaseInput(TraceInputModel):
    event_type: str = Field(min_length=1, max_length=120)
    actor_id: str | None = Field(default=None, min_length=1, max_length=255)
    actor_type: ActorType = "system"
    workspace_id: uuid.UUID | None = None
    object_id: uuid.UUID | None = None
    object_type: str | None = Field(default=None, min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=120)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("event_type", "actor_id", "object_type", "operation")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("trace text fields must not be blank")
        return trimmed

    @model_validator(mode="after")
    def object_metadata_is_coherent(self) -> TraceEventBaseInput:
        if (self.object_id is None) != (self.object_type is None):
            raise ValueError("objectId and objectType must be supplied together")
        return self


class StartTraceInput(TraceEventBaseInput):
    trace_id: uuid.UUID | None = None
    parent_trace_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def trace_is_not_own_parent(self) -> StartTraceInput:
        if self.trace_id is not None and self.trace_id == self.parent_trace_id:
            raise ValueError("a trace cannot be its own parent")
        return self


class RecordTraceEventInput(TraceEventBaseInput):
    trace_id: uuid.UUID
    parent_trace_id: uuid.UUID | None = None
    status: TraceStatus
    error: TraceErrorInfo | None = None

    @model_validator(mode="after")
    def status_and_error_are_coherent(self) -> RecordTraceEventInput:
        if self.trace_id == self.parent_trace_id:
            raise ValueError("a trace cannot be its own parent")
        if self.status == "failed" and self.error is None:
            raise ValueError("failed trace events require structured error information")
        if self.status != "failed" and self.error is not None:
            raise ValueError("only failed trace events may contain error information")
        return self


class CompleteTraceInput(TraceEventBaseInput):
    trace_id: uuid.UUID
    parent_trace_id: uuid.UUID | None = None


class FailTraceInput(CompleteTraceInput):
    error: TraceErrorInfo


class TraceQueryFilters(TraceInputModel):
    trace_id: uuid.UUID | None = None
    parent_trace_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    object_id: uuid.UUID | None = None
    event_type: str | None = Field(default=None, min_length=1, max_length=120)
    actor_type: ActorType | None = None
    status: TraceStatus | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=100_000)

    @field_validator("event_type")
    @classmethod
    def trim_event_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("eventType must not be blank")
        return trimmed


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: uuid.UUID
    parent_trace_id: uuid.UUID | None
    start_event: TraceEvent


class TracePersistenceError(RuntimeError):
    """Raised when a validated Trace event cannot be persisted."""


class TraceService:
    """Reusable persistent Trace lifecycle and query service.

    The service participates in the caller's database transaction and never commits it. This keeps
    a domain mutation and its required success event atomic. Callers recording a failed operation
    should roll back the failed mutation first, then append and commit the failure event.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._last_occurred_at_by_trace: dict[uuid.UUID, datetime] = {}

    async def start_trace(self, input_data: StartTraceInput) -> TraceContext:
        trace_id = input_data.trace_id or uuid.uuid4()
        event = await self.record_event(
            RecordTraceEventInput(
                trace_id=trace_id,
                parent_trace_id=input_data.parent_trace_id,
                event_type=input_data.event_type,
                actor_id=input_data.actor_id,
                actor_type=input_data.actor_type,
                workspace_id=input_data.workspace_id,
                object_id=input_data.object_id,
                object_type=input_data.object_type,
                operation=input_data.operation,
                status="started",
                metadata=input_data.metadata,
            )
        )
        return TraceContext(
            trace_id=trace_id,
            parent_trace_id=input_data.parent_trace_id,
            start_event=event,
        )

    async def record_event(self, input_data: RecordTraceEventInput) -> TraceEvent:
        occurred_at = datetime.now(UTC)
        previous_occurred_at = self._last_occurred_at_by_trace.get(input_data.trace_id)
        if previous_occurred_at is not None and occurred_at <= previous_occurred_at:
            occurred_at = previous_occurred_at + timedelta(microseconds=1)
        self._last_occurred_at_by_trace[input_data.trace_id] = occurred_at
        event = TraceEvent(
            trace_id=input_data.trace_id,
            parent_trace_id=input_data.parent_trace_id,
            occurred_at=occurred_at,
            event_type=input_data.event_type,
            actor_id=input_data.actor_id,
            actor_type=input_data.actor_type,
            workspace_id=input_data.workspace_id,
            object_id=input_data.object_id,
            object_type=input_data.object_type,
            operation=input_data.operation,
            status=input_data.status,
            metadata_payload=_json_object(input_data.metadata),
            error_payload=(
                _json_object(input_data.error.model_dump(mode="json"))
                if input_data.error is not None
                else None
            ),
        )
        self._session.add(event)
        try:
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise TracePersistenceError("Trace event persistence failed") from exc
        return event

    async def complete_trace(self, input_data: CompleteTraceInput) -> TraceEvent:
        return await self.record_event(
            RecordTraceEventInput(
                **input_data.model_dump(),
                status="succeeded",
            )
        )

    async def fail_trace(self, input_data: FailTraceInput) -> TraceEvent:
        return await self.record_event(
            RecordTraceEventInput(
                **input_data.model_dump(exclude={"error"}),
                status="failed",
                error=input_data.error,
            )
        )

    async def get_trace(self, trace_id: uuid.UUID) -> list[TraceEvent]:
        return await self.query_trace_events(TraceQueryFilters(trace_id=trace_id, limit=500))

    async def query_trace_events(self, filters: TraceQueryFilters) -> list[TraceEvent]:
        statement: Select[tuple[TraceEvent]] = select(TraceEvent)
        if filters.trace_id is not None:
            statement = statement.where(TraceEvent.trace_id == filters.trace_id)
        if filters.parent_trace_id is not None:
            statement = statement.where(TraceEvent.parent_trace_id == filters.parent_trace_id)
        if filters.workspace_id is not None:
            statement = statement.where(TraceEvent.workspace_id == filters.workspace_id)
        if filters.object_id is not None:
            statement = statement.where(TraceEvent.object_id == filters.object_id)
        if filters.event_type is not None:
            statement = statement.where(TraceEvent.event_type == filters.event_type)
        if filters.actor_type is not None:
            statement = statement.where(TraceEvent.actor_type == filters.actor_type)
        if filters.status is not None:
            statement = statement.where(TraceEvent.status == filters.status)
        statement = statement.order_by(TraceEvent.occurred_at, TraceEvent.event_id)
        statement = statement.offset(filters.offset).limit(filters.limit)
        return list((await self._session.scalars(statement)).all())


def _json_object(value: dict[str, JsonValue] | dict[str, object]) -> dict[str, object]:
    """Return a detached JSON-safe object and reject NaN or custom Python values."""

    serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    decoded = json.loads(serialized)
    if not isinstance(decoded, dict):
        raise ValueError("Trace payload must be a JSON object")
    return cast(dict[str, object], decoded)


__all__ = [
    "ActorType",
    "CompleteTraceInput",
    "FailTraceInput",
    "RecordTraceEventInput",
    "StartTraceInput",
    "TraceContext",
    "TraceErrorInfo",
    "TracePersistenceError",
    "TraceQueryFilters",
    "TraceService",
    "TraceStatus",
]
