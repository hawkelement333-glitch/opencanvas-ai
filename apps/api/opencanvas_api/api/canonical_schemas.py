from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.services.canonical.lifecycle import LifecycleState
from opencanvas_api.services.canonical.service import (
    CanonicalObjectType,
    DocumentProcessingStatus,
    ExecutionStatus,
    JsonObject,
    RelationshipType,
)


class MutationContext(ApiModel):
    actor_id: str | None = Field(default=None, min_length=1, max_length=255)
    parent_trace_id: uuid.UUID | None = None

    @field_validator("actor_id")
    @classmethod
    def trim_actor_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("actorId must not be blank")
        return trimmed


class WorkspaceCreate(MutationContext):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=20_000)
    owner_id: uuid.UUID | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def trim_workspace_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed


class WorkspaceUpdate(MutationContext):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=20_000)
    owner_id: uuid.UUID | None = None
    metadata: JsonObject | None = None

    @field_validator("name")
    @classmethod
    def trim_optional_workspace_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed

    @model_validator(mode="after")
    def contains_workspace_change(self) -> Self:
        mutable_fields = {"name", "description", "owner_id", "metadata"}
        if not (self.model_fields_set & mutable_fields):
            raise ValueError("at least one workspace field must be supplied")
        return self


class LifecycleTransition(MutationContext):
    expected_version: int = Field(ge=1)
    target_state: LifecycleState


class WorkspaceOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    owner_id: uuid.UUID | None = None
    version: int = Field(ge=1)
    lifecycle_state: LifecycleState
    metadata: JsonObject = Field(default_factory=dict)
    legacy_canvas_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class CanonicalObjectOut(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    object_type: CanonicalObjectType
    version: int = Field(ge=1)
    lifecycle_state: LifecycleState
    metadata: JsonObject = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ObjectMutation(MutationContext):
    metadata: JsonObject = Field(default_factory=dict)


class ObjectUpdate(MutationContext):
    expected_version: int = Field(ge=1)
    metadata: JsonObject | None = None


class DocumentCreate(ObjectMutation):
    display_name: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=64)
    processing_status: DocumentProcessingStatus = "created"
    source_metadata: JsonObject = Field(default_factory=dict)
    legacy_document_id: uuid.UUID | None = None

    @field_validator("display_name", "source_type")
    @classmethod
    def trim_document_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("document text fields must not be blank")
        return trimmed


class DocumentUpdate(ObjectUpdate):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    processing_status: DocumentProcessingStatus | None = None
    source_metadata: JsonObject | None = None

    @field_validator("display_name", "source_type")
    @classmethod
    def trim_optional_document_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("document text fields must not be blank")
        return trimmed

    @model_validator(mode="after")
    def contains_document_change(self) -> Self:
        mutable_fields = {
            "display_name",
            "source_type",
            "processing_status",
            "source_metadata",
            "metadata",
        }
        if not (self.model_fields_set & mutable_fields):
            raise ValueError("at least one document field must be supplied")
        return self


class DocumentOut(CanonicalObjectOut):
    object_type: Literal["document"] = "document"
    display_name: str
    source_type: str
    processing_status: DocumentProcessingStatus
    source_metadata: JsonObject = Field(default_factory=dict)
    legacy_document_id: uuid.UUID | None = None


class ChunkCreate(ObjectMutation):
    document_object_id: uuid.UUID
    ordered_position: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=1_000_000)
    source_location: JsonObject = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def reject_blank_chunk(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class ChunkUpdate(ObjectUpdate):
    ordered_position: int | None = Field(default=None, ge=0)
    content: str | None = Field(default=None, min_length=1, max_length=1_000_000)
    source_location: JsonObject | None = None

    @field_validator("content")
    @classmethod
    def reject_optional_blank_chunk(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("content must not be blank")
        return value

    @model_validator(mode="after")
    def contains_chunk_change(self) -> Self:
        mutable_fields = {"ordered_position", "content", "source_location", "metadata"}
        if not (self.model_fields_set & mutable_fields):
            raise ValueError("at least one chunk field must be supplied")
        return self


class ChunkOut(CanonicalObjectOut):
    object_type: Literal["chunk"] = "chunk"
    document_object_id: uuid.UUID
    ordered_position: int = Field(ge=0)
    content: str
    source_location: JsonObject = Field(default_factory=dict)


class NoteCreate(ObjectMutation):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", max_length=1_000_000)

    @field_validator("title")
    @classmethod
    def trim_note_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("title must not be blank")
        return trimmed


class NoteUpdate(ObjectUpdate):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=1_000_000)

    @field_validator("title")
    @classmethod
    def trim_optional_note_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("title must not be blank")
        return trimmed

    @model_validator(mode="after")
    def contains_note_change(self) -> Self:
        mutable_fields = {"title", "content", "metadata"}
        if not (self.model_fields_set & mutable_fields):
            raise ValueError("at least one note field must be supplied")
        return self


class NoteOut(CanonicalObjectOut):
    object_type: Literal["note"] = "note"
    title: str
    content: str


class ExecutionCreate(ObjectMutation):
    execution_type: str = Field(min_length=1, max_length=64)
    status: ExecutionStatus = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    trace_id: uuid.UUID | None = None
    inputs_metadata: JsonObject = Field(default_factory=dict)
    outputs_metadata: JsonObject = Field(default_factory=dict)
    failure: JsonObject | None = None

    @field_validator("execution_type")
    @classmethod
    def trim_execution_type(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("executionType must not be blank")
        return trimmed

    @model_validator(mode="after")
    def execution_fields_are_coherent(self) -> Self:
        _validate_execution_fields(
            status=self.status,
            started_at=self.started_at,
            completed_at=self.completed_at,
            failure=self.failure,
        )
        return self


class ExecutionUpdate(ObjectUpdate):
    execution_type: str | None = Field(default=None, min_length=1, max_length=64)
    status: ExecutionStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    trace_id: uuid.UUID | None = None
    inputs_metadata: JsonObject | None = None
    outputs_metadata: JsonObject | None = None
    failure: JsonObject | None = None

    @field_validator("execution_type")
    @classmethod
    def trim_optional_execution_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("executionType must not be blank")
        return trimmed

    @model_validator(mode="after")
    def contains_execution_change(self) -> Self:
        mutable_fields = {
            "execution_type",
            "status",
            "started_at",
            "completed_at",
            "trace_id",
            "inputs_metadata",
            "outputs_metadata",
            "failure",
            "metadata",
        }
        if not (self.model_fields_set & mutable_fields):
            raise ValueError("at least one execution field must be supplied")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completedAt must not precede startedAt")
        return self


class ExecutionOut(CanonicalObjectOut):
    object_type: Literal["execution"] = "execution"
    execution_type: str
    status: ExecutionStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    trace_id: uuid.UUID | None = None
    inputs_metadata: JsonObject = Field(default_factory=dict)
    outputs_metadata: JsonObject = Field(default_factory=dict)
    failure: JsonObject | None = None


class RelationshipCreate(MutationContext):
    relationship_type: RelationshipType
    source_object_id: uuid.UUID
    target_object_id: uuid.UUID
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def rejects_self_relationship(self) -> Self:
        if self.source_object_id == self.target_object_id:
            raise ValueError("a canonical relationship cannot reference itself")
        return self


class RelationshipOut(CanonicalObjectOut):
    object_type: Literal["relationship"] = "relationship"
    relationship_type: RelationshipType
    source_object_id: uuid.UUID
    target_object_id: uuid.UUID
    created_by: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None


def _validate_execution_fields(
    *,
    status: ExecutionStatus,
    started_at: datetime | None,
    completed_at: datetime | None,
    failure: JsonObject | None,
) -> None:
    if started_at is not None and completed_at is not None and completed_at < started_at:
        raise ValueError("completedAt must not precede startedAt")
    if status == "failed" and failure is None:
        raise ValueError("failed executions require failure details")
    if status != "failed" and failure is not None:
        raise ValueError("only failed executions may contain failure details")


__all__ = [
    "CanonicalObjectOut",
    "CanonicalObjectType",
    "ChunkCreate",
    "ChunkOut",
    "ChunkUpdate",
    "DocumentCreate",
    "DocumentOut",
    "DocumentProcessingStatus",
    "DocumentUpdate",
    "ExecutionCreate",
    "ExecutionOut",
    "ExecutionStatus",
    "ExecutionUpdate",
    "JsonObject",
    "LifecycleState",
    "LifecycleTransition",
    "NoteCreate",
    "NoteOut",
    "NoteUpdate",
    "RelationshipCreate",
    "RelationshipOut",
    "RelationshipType",
    "WorkspaceCreate",
    "WorkspaceOut",
    "WorkspaceUpdate",
]
