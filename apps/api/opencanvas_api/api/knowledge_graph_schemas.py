from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.services.knowledge_graph import (
    GraphEntityKind,
    GraphHistoryState,
    GraphRelationshipType,
)


class GraphEntityReferenceIn(ApiModel):
    kind: GraphEntityKind
    object_id: uuid.UUID


class GraphRelationshipCreateIn(ApiModel):
    relationship_type: GraphRelationshipType
    source: GraphEntityReferenceIn
    target: GraphEntityReferenceIn
    idempotency_key: str = Field(min_length=1, max_length=128)
    parent_trace_id: uuid.UUID | None = None

    @field_validator("idempotency_key")
    @classmethod
    def trim_idempotency_key(cls, value: str) -> str:
        if not (trimmed := value.strip()):
            raise ValueError("idempotencyKey must not be blank")
        return trimmed

    @model_validator(mode="after")
    def rejects_self_reference(self) -> GraphRelationshipCreateIn:
        if self.source.object_id == self.target.object_id:
            raise ValueError("a knowledge graph relationship cannot reference itself")
        return self


class GraphRelationshipTransitionIn(ApiModel):
    expected_version: int = Field(ge=1)
    target_state: Literal["inactive", "superseded", "rejected"] = "inactive"
    reason_code: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    parent_trace_id: uuid.UUID | None = None

    @field_validator("reason_code", "idempotency_key")
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not (trimmed := value.strip()):
            raise ValueError("graph transition text must not be blank")
        return trimmed


class GraphEntityReferenceOut(ApiModel):
    kind: GraphEntityKind
    object_id: uuid.UUID


class GraphProvenanceOut(ApiModel):
    provenance_id: uuid.UUID
    origin_type: Literal[
        "user_created",
        "imported_canonical",
        "citation_derived",
        "controlled_agent_approved",
        "deterministic_rule",
    ]
    actor_user_id: uuid.UUID
    execution_id: uuid.UUID | None
    source_reference_id: uuid.UUID | None
    rule_id: str | None
    rule_version: str | None
    trace_id: uuid.UUID
    provenance_digest: str
    created_at: datetime


class GraphHistoryOut(ApiModel):
    history_id: uuid.UUID
    state: GraphHistoryState
    reason_code: str | None
    actor_user_id: uuid.UUID
    trace_id: uuid.UUID
    graph_revision: int
    previous_history_id: uuid.UUID | None
    created_at: datetime


class GraphRelationshipOut(ApiModel):
    relationship_id: uuid.UUID
    relationship_type: GraphRelationshipType
    source: GraphEntityReferenceOut
    target: GraphEntityReferenceOut
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    version: int
    lifecycle_state: str
    graph_revision: int
    canonical_digest: str
    current_state: GraphHistoryState
    provenance: GraphProvenanceOut
    created_at: datetime
    replayed: bool = False


__all__ = [
    "GraphHistoryOut",
    "GraphRelationshipCreateIn",
    "GraphRelationshipOut",
    "GraphRelationshipTransitionIn",
]
