from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import JsonValue

from opencanvas_api.api.schemas import ApiModel

SafeActivityStatus = Literal[
    "pending_delivery",
    "actively_delivering",
    "delivered",
    "retry_waiting",
    "terminal_delivery_failure",
]


class DomainEventProvenanceOut(ApiModel):
    provenance_id: uuid.UUID
    origin_type: Literal[
        "authenticated_user",
        "canonical_service",
        "controlled_execution",
        "reserved_future_contract",
    ]
    actor_user_id: uuid.UUID
    trace_id: uuid.UUID
    audit_event_id: uuid.UUID | None
    execution_id: uuid.UUID | None
    graph_relationship_id: uuid.UUID | None
    graph_history_id: uuid.UUID | None
    effect_id: uuid.UUID | None
    rollback_result_id: uuid.UUID | None
    provenance_digest: str


class DomainEventDeliveryOut(ApiModel):
    status: SafeActivityStatus
    attempt_count: int
    max_attempts: int
    eligible_at: datetime
    failure_classification: str | None
    completed_at: datetime | None
    terminal_at: datetime | None


class DomainEventOut(ApiModel):
    event_id: uuid.UUID
    event_type: str
    registry_version: str
    schema_version: str
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID | None
    sequence: int
    subject_kind: str
    subject_id: uuid.UUID
    related_id: uuid.UUID | None
    actor_user_id: uuid.UUID
    execution_id: uuid.UUID | None
    graph_revision: int | None
    occurred_at: datetime
    payload: dict[str, JsonValue]
    payload_digest: str
    trace_id: uuid.UUID
    audit_event_id: uuid.UUID | None
    provenance: DomainEventProvenanceOut
    delivery: DomainEventDeliveryOut


class DomainActivityOut(ApiModel):
    event_id: uuid.UUID
    event_type: str
    sequence: int
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID | None
    subject_kind: str
    subject_id: uuid.UUID
    actor_user_id: uuid.UUID
    execution_id: uuid.UUID | None
    graph_revision: int | None
    trace_id: uuid.UUID
    occurred_at: datetime
    status: SafeActivityStatus
    projected: bool


__all__ = [
    "DomainActivityOut",
    "DomainEventDeliveryOut",
    "DomainEventOut",
    "DomainEventProvenanceOut",
]
