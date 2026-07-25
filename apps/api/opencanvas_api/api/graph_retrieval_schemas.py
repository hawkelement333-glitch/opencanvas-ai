from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from opencanvas_api.api.schemas import ApiModel


class StartGraphRetrievalIn(ApiModel):
    query: str = Field(min_length=1, max_length=4_000)
    selected_object_ids: tuple[uuid.UUID, ...] = Field(min_length=1, max_length=50)
    seed_object_ids: tuple[uuid.UUID, ...] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=1, max_length=128)
    mode: Literal["selected_graph"] = "selected_graph"
    max_depth: int = Field(default=2, ge=0, le=3)
    top_k: int = Field(default=8, ge=1, le=50)
    min_relevance: float = Field(default=0.15, ge=-1, le=1)


class RetrievalDecisionOut(ApiModel):
    decision_id: uuid.UUID
    object_id: uuid.UUID
    relationship_id: uuid.UUID | None
    included: bool
    reason_code: str
    distance: int
    rank: int | None
    score: float | None
    relationship_path: list[uuid.UUID]


class RetrievalCitationOut(ApiModel):
    citation_id: uuid.UUID
    canonical_object_id: uuid.UUID
    canonical_version: int
    source_version: int
    source_sha256: str
    source_title: str
    source_type: str
    passage_identity: str
    excerpt: str
    excerpt_sha256: str
    locator: dict[str, object]
    relationship_path: list[uuid.UUID]
    graph_revision: int
    ordinal: int
    citation_schema_version: str
    trace_id: uuid.UUID


class GraphRetrievalOut(ApiModel):
    retrieval_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    query: str
    selected_object_ids: list[uuid.UUID]
    seed_object_ids: list[uuid.UUID]
    graph_revision: int
    algorithm_version: str
    schema_version: str
    mode: str
    outcome: str
    bounded: bool
    trace_id: uuid.UUID
    created_at: datetime
    duplicate: bool
    decisions: list[RetrievalDecisionOut]
    citations: list[RetrievalCitationOut]


class ApaCitationOut(ApiModel):
    citation_id: uuid.UUID
    in_text: str
    reference: str


class ApaRenderOut(ApiModel):
    renderer_version: str
    citations: list[ApaCitationOut]


class EvidenceBundleRequest(ApiModel):
    include_authorized_sources: bool = False


class EvidenceBundleOut(ApiModel):
    bundle_id: uuid.UUID
    retrieval_id: uuid.UUID
    schema_version: str
    state: str
    artifact_sha256: str | None
    byte_size: int
    manifest: dict[str, object]
    trace_id: uuid.UUID
    created_at: datetime


class RetrievalTraceSummaryOut(ApiModel):
    trace_id: uuid.UUID
    statuses: list[str]
    event_types: list[str]
    safe_metadata: list[dict[str, object]]


__all__ = [
    "ApaCitationOut",
    "ApaRenderOut",
    "EvidenceBundleOut",
    "EvidenceBundleRequest",
    "GraphRetrievalOut",
    "RetrievalCitationOut",
    "RetrievalDecisionOut",
    "RetrievalTraceSummaryOut",
    "StartGraphRetrievalIn",
]
