from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
        allow_inf_nan=False,
    )


class Point(ApiModel):
    x: float
    y: float


class Viewport(Point):
    zoom: float = Field(gt=0, le=8.0)


class CanvasCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed


class CanvasPatch(ApiModel):
    revision: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    viewport: Viewport | None = None

    @field_validator("name")
    @classmethod
    def trim_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed

    @model_validator(mode="after")
    def contains_change(self) -> Self:
        if self.name is None and self.viewport is None:
            raise ValueError("at least one canvas field must be supplied")
        return self


class CanvasOut(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    viewport: Viewport
    revision: int
    created_at: datetime
    updated_at: datetime


DocumentFileType = Literal["pdf", "txt", "markdown", "docx"]
DocumentStatus = Literal[
    "uploaded",
    "queued",
    "processing",
    "ready",
    "retryable_failure",
    "retrying",
    "permanent_failure",
    "deleting",
    "deleted",
    "failed",
]
DocumentProcessingStage = Literal[
    "uploading",
    "queued",
    "validating",
    "extracting",
    "chunking",
    "embedding",
    "indexing",
    "ready",
    "retrying",
    "deleting",
    "deleted",
    "failed",
]
NodeType = Literal["note", "ai_response", "document"]
EdgeKind = Literal["default", "generated_from", "cites"]


class DocumentMetadata(ApiModel):
    id: uuid.UUID
    canvas_id: uuid.UUID
    file_name: str
    file_type: DocumentFileType
    media_type: str
    file_size: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=1)
    status: DocumentStatus
    processing_stage: DocumentProcessingStage
    error_message: str | None = None
    chunk_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class CitationOut(ApiModel):
    id: uuid.UUID
    source_id: str
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID
    page_number: int | None = Field(default=None, ge=1)
    heading: str | None = None
    chunk_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    excerpt: str
    claim: str = Field(max_length=4_000)
    ordinal: int = Field(ge=1)

    @model_validator(mode="after")
    def citation_offsets_are_ordered(self) -> Self:
        if self.end_offset <= self.start_offset:
            raise ValueError("endOffset must be greater than startOffset")
        return self


class NodeCreate(ApiModel):
    type: NodeType = "note"
    title: str = Field(default="Untitled note", min_length=1, max_length=160)
    text: str = Field(default="", max_length=100_000)
    position: Point
    width: float = Field(default=300.0, ge=220.0, le=1600.0)
    height: float = Field(default=220.0, ge=140.0, le=1200.0)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("title must not be blank")
        return trimmed


class NodePatch(ApiModel):
    revision: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    text: str | None = Field(default=None, max_length=100_000)
    position: Point | None = None
    width: float | None = Field(default=None, ge=220.0, le=1600.0)
    height: float | None = Field(default=None, ge=140.0, le=1200.0)

    @field_validator("title")
    @classmethod
    def trim_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("title must not be blank")
        return trimmed

    @model_validator(mode="after")
    def contains_change(self) -> Self:
        changed = (self.title, self.text, self.position, self.width, self.height)
        if all(value is None for value in changed):
            raise ValueError("at least one node field must be supplied")
        return self


class NodeDuplicate(ApiModel):
    revision: int = Field(ge=0)
    position: Point | None = None


class NodeOut(ApiModel):
    id: uuid.UUID
    canvas_id: uuid.UUID
    type: NodeType
    title: str
    text: str
    position: Point
    width: float
    height: float
    revision: int
    created_at: datetime
    updated_at: datetime
    document: DocumentMetadata | None = None
    citations: list[CitationOut] = Field(default_factory=list)


class EdgeCreate(ApiModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    kind: EdgeKind = "default"
    label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def rejects_self_edge(self) -> Self:
        if self.source_node_id == self.target_node_id:
            raise ValueError("an edge cannot connect a node to itself")
        return self


class EdgeOut(ApiModel):
    id: uuid.UUID
    canvas_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    kind: EdgeKind
    label: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class SnapshotOut(ApiModel):
    canvas: CanvasOut
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class AIQuery(ApiModel):
    instruction: str = Field(min_length=1, max_length=8_000)
    selected_node_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)

    @field_validator("instruction")
    @classmethod
    def trim_instruction(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("instruction must not be blank")
        return trimmed

    @field_validator("selected_node_ids")
    @classmethod
    def deduplicate_selected_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("selectedNodeIds must not contain duplicates")
        return value


class AIQueryOut(ApiModel):
    request_id: uuid.UUID
    response_id: uuid.UUID
    trace_id: uuid.UUID
    node: NodeOut
    edges: list[EdgeOut]
    mock: bool
    grounded: bool = False
    insufficient_evidence: bool = False
    citations: list[CitationOut] = Field(default_factory=list)
    parent_request_id: uuid.UUID | None = None
    rerun_type: Literal["original_context", "current_context"] | None = None


class UploadDocumentOut(ApiModel):
    document: DocumentMetadata
    node: NodeOut


class DocumentTextSection(ApiModel):
    page_number: int | None = Field(default=None, ge=1)
    heading: str | None = None
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> Self:
        if self.end_offset < self.start_offset:
            raise ValueError("endOffset must be greater than or equal to startOffset")
        return self


class DocumentTextOut(ApiModel):
    document_id: uuid.UUID
    file_name: str
    text: str
    sections: list[DocumentTextSection]


class SourcePassageOut(ApiModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    document_title: str
    page_number: int | None = Field(default=None, ge=1)
    heading: str | None = None
    chunk_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    text: str


class DocumentSearchRequest(ApiModel):
    query: str = Field(min_length=1, max_length=8_000)
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    top_k: int | None = Field(default=None, ge=1, le=20)
    min_relevance: float | None = Field(default=None, ge=-1.0, le=1.0)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("query must not be blank")
        return trimmed

    @field_validator("document_ids")
    @classmethod
    def deduplicate_document_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("documentIds must not contain duplicates")
        return value


class DocumentSearchMatch(SourcePassageOut):
    score: float = Field(ge=-1.0, le=1.0)


class DocumentSearchOut(ApiModel):
    query: str
    matches: list[DocumentSearchMatch]
    insufficient_context: bool
