from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, JsonValue

from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.services.trace import ActorType, TraceStatus


class TraceErrorOut(ApiModel):
    code: str | None = None
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class TraceEventOut(ApiModel):
    event_id: uuid.UUID
    trace_id: uuid.UUID
    parent_trace_id: uuid.UUID | None = None
    timestamp: datetime
    event_type: str
    actor_id: str | None = None
    actor_type: ActorType
    workspace_id: uuid.UUID | None = None
    object_id: uuid.UUID | None = None
    object_type: str | None = None
    operation: str
    status: TraceStatus
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    error: TraceErrorOut | None = None
