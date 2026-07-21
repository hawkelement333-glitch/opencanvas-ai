from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import NoReturn, cast

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalExecution,
    CanonicalNote,
    CanonicalObject,
    CanonicalRelationship,
    Document,
    Workspace,
)
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalNotFoundError,
    CanonicalStorageError,
    CanonicalValidationError,
    LifecycleState,
    WorkspaceBoundaryError,
    ensure_transition,
)

type CanonicalDetail = (
    CanonicalDocument | CanonicalChunk | CanonicalNote | CanonicalExecution | CanonicalRelationship
)


@dataclass(frozen=True, slots=True)
class CanonicalAggregate:
    object: CanonicalObject
    detail: CanonicalDetail


class CanonicalRepository:
    """Workspace-isolated canonical persistence with optimistic, monotonic versions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        description: str | None,
        owner_id: uuid.UUID | None,
        lifecycle_state: LifecycleState,
        metadata_payload: dict[str, object],
    ) -> Workspace:
        workspace = Workspace(
            id=workspace_id,
            name=name,
            description=description,
            owner_id=owner_id or SYSTEM_USER_ID,
            version=1,
            lifecycle_state=lifecycle_state.value,
            metadata_payload=metadata_payload,
        )
        self.session.add(workspace)
        await self._flush("Workspace persistence failed.")
        return workspace

    async def get_workspace(
        self, workspace_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Workspace:
        statement = select(Workspace).where(Workspace.id == workspace_id)
        if not include_deleted:
            statement = statement.where(Workspace.lifecycle_state != LifecycleState.DELETED.value)
        try:
            workspace = await self.session.scalar(statement)
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Workspace lookup failed.") from exc
        if workspace is None:
            raise CanonicalNotFoundError("Workspace not found.")
        return workspace

    async def list_workspaces(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        lifecycle_state: LifecycleState | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Workspace]:
        statement: Select[tuple[Workspace]] = select(Workspace)
        if owner_id is not None:
            statement = statement.where(Workspace.owner_id == owner_id)
        if lifecycle_state is not None:
            statement = statement.where(Workspace.lifecycle_state == lifecycle_state.value)
        elif not include_deleted:
            statement = statement.where(Workspace.lifecycle_state != LifecycleState.DELETED.value)
        statement = (
            statement.order_by(Workspace.created_at, Workspace.id).offset(offset).limit(limit)
        )
        try:
            return list((await self.session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Workspace listing failed.") from exc

    async def update_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
        expected_version: int,
        name: str,
        description: str | None,
        owner_id: uuid.UUID | None,
        metadata_payload: dict[str, object],
    ) -> Workspace:
        workspace = await self._update_workspace_row(
            workspace_id=workspace_id,
            expected_version=expected_version,
            values={
                "name": name,
                "description": description,
                "owner_id": owner_id,
                "metadata_payload": metadata_payload,
            },
        )
        await self._flush("Workspace update failed.")
        return workspace

    async def transition_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
        expected_version: int,
        target_state: LifecycleState,
    ) -> Workspace:
        current = await self.get_workspace(workspace_id, include_deleted=True)
        if current.version != expected_version:
            raise CanonicalConflictError("Workspace version is stale.")
        normalized_target = ensure_transition(current.lifecycle_state, target_state)
        workspace = await self._update_workspace_row(
            workspace_id=workspace_id,
            expected_version=expected_version,
            values={"lifecycle_state": normalized_target.value},
            allow_archived=True,
        )
        await self._flush("Workspace transition failed.")
        return workspace

    async def create_object(
        self,
        *,
        object_id: uuid.UUID,
        workspace_id: uuid.UUID,
        object_type: str,
        lifecycle_state: LifecycleState,
        metadata_payload: dict[str, object],
        detail: CanonicalDetail,
    ) -> CanonicalAggregate:
        workspace = await self.get_workspace(workspace_id)
        if workspace.lifecycle_state == LifecycleState.ARCHIVED.value:
            raise CanonicalConflictError("Archived workspaces cannot accept new objects.")
        if detail.object_id != object_id:
            raise CanonicalStorageError("Canonical detail identity does not match its object.")
        detail_type_by_object_type = {
            "document": CanonicalDocument,
            "chunk": CanonicalChunk,
            "note": CanonicalNote,
            "execution": CanonicalExecution,
            "relationship": CanonicalRelationship,
        }
        expected_detail_type = detail_type_by_object_type.get(object_type)
        if expected_detail_type is None or not isinstance(detail, expected_detail_type):
            raise CanonicalStorageError("Canonical detail does not match its object type.")
        if isinstance(detail, CanonicalChunk):
            parent = await self.get_object(workspace_id, detail.document_object_id)
            if not isinstance(parent.detail, CanonicalDocument):
                raise CanonicalValidationError(
                    "Canonical chunks must reference a document in the same workspace."
                )
        canonical_object = CanonicalObject(
            id=object_id,
            workspace_id=workspace_id,
            object_type=object_type,
            version=1,
            lifecycle_state=lifecycle_state.value,
            metadata_payload=metadata_payload,
        )
        self.session.add(canonical_object)
        await self._flush("Canonical object persistence failed.")
        self.session.add(detail)
        await self._flush("Canonical object persistence failed.")
        return CanonicalAggregate(object=canonical_object, detail=detail)

    async def get_object(
        self,
        workspace_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> CanonicalAggregate:
        await self.get_workspace(workspace_id, include_deleted=include_deleted)
        statement = select(CanonicalObject).where(
            CanonicalObject.id == object_id,
            CanonicalObject.workspace_id == workspace_id,
        )
        if not include_deleted:
            statement = statement.where(
                CanonicalObject.lifecycle_state != LifecycleState.DELETED.value
            )
        try:
            canonical_object = await self.session.scalar(statement)
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Canonical object lookup failed.") from exc
        if canonical_object is None:
            await self._raise_object_boundary_or_missing(workspace_id, object_id)
        detail = await self._get_detail(canonical_object)
        return CanonicalAggregate(object=canonical_object, detail=detail)

    async def list_objects(
        self,
        workspace_id: uuid.UUID,
        *,
        object_type: str | None = None,
        lifecycle_state: LifecycleState | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CanonicalAggregate]:
        await self.get_workspace(workspace_id, include_deleted=include_deleted)
        statement: Select[tuple[CanonicalObject]] = select(CanonicalObject).where(
            CanonicalObject.workspace_id == workspace_id
        )
        if object_type is not None:
            statement = statement.where(CanonicalObject.object_type == object_type)
        if lifecycle_state is not None:
            statement = statement.where(CanonicalObject.lifecycle_state == lifecycle_state.value)
        elif not include_deleted:
            statement = statement.where(
                CanonicalObject.lifecycle_state != LifecycleState.DELETED.value
            )
        statement = (
            statement.order_by(CanonicalObject.created_at, CanonicalObject.id)
            .offset(offset)
            .limit(limit)
        )
        try:
            objects = list((await self.session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Canonical object listing failed.") from exc
        return [CanonicalAggregate(item, await self._get_detail(item)) for item in objects]

    async def update_object_metadata(
        self,
        *,
        workspace_id: uuid.UUID,
        object_id: uuid.UUID,
        expected_version: int,
        metadata_payload: dict[str, object],
    ) -> CanonicalAggregate:
        canonical_object = await self._update_object_row(
            workspace_id=workspace_id,
            object_id=object_id,
            expected_version=expected_version,
            values={"metadata_payload": metadata_payload},
        )
        await self._flush("Canonical object update failed.")
        return CanonicalAggregate(canonical_object, await self._get_detail(canonical_object))

    async def validate_legacy_document(
        self, workspace_id: uuid.UUID, legacy_document_id: uuid.UUID
    ) -> None:
        workspace = await self.get_workspace(workspace_id)
        if workspace.legacy_canvas_id is None:
            raise CanonicalValidationError(
                "Legacy documents require a workspace linked to their canvas."
            )
        try:
            legacy_canvas_id = await self.session.scalar(
                select(Document.canvas_id).where(Document.id == legacy_document_id)
            )
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Legacy document validation failed.") from exc
        if legacy_canvas_id != workspace.legacy_canvas_id:
            raise CanonicalValidationError(
                "legacy_document_id must belong to the workspace's legacy canvas."
            )

    async def transition_object(
        self,
        *,
        workspace_id: uuid.UUID,
        object_id: uuid.UUID,
        expected_version: int,
        target_state: LifecycleState,
    ) -> CanonicalAggregate:
        workspace = await self.get_workspace(workspace_id)
        if workspace.lifecycle_state == LifecycleState.ARCHIVED.value:
            raise CanonicalConflictError("Archived workspaces cannot mutate child objects.")
        current = await self.get_object(workspace_id, object_id, include_deleted=True)
        if current.object.version != expected_version:
            raise CanonicalConflictError("Canonical object version is stale.")
        normalized_target = ensure_transition(current.object.lifecycle_state, target_state)
        canonical_object = await self._update_object_row(
            workspace_id=workspace_id,
            object_id=object_id,
            expected_version=expected_version,
            values={"lifecycle_state": normalized_target.value},
            allow_archived=True,
        )
        await self._flush("Canonical object transition failed.")
        return CanonicalAggregate(canonical_object, await self._get_detail(canonical_object))

    async def flush(self) -> None:
        await self._flush("Canonical persistence failed.")

    async def list_relationships(
        self,
        workspace_id: uuid.UUID,
        *,
        relationship_type: str | None = None,
        source_object_id: uuid.UUID | None = None,
        target_object_id: uuid.UUID | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CanonicalAggregate]:
        await self.get_workspace(workspace_id, include_deleted=include_deleted)
        statement: Select[tuple[CanonicalObject]] = (
            select(CanonicalObject)
            .join(
                CanonicalRelationship,
                CanonicalRelationship.object_id == CanonicalObject.id,
            )
            .where(CanonicalObject.workspace_id == workspace_id)
        )
        if relationship_type is not None:
            statement = statement.where(
                CanonicalRelationship.relationship_type == relationship_type
            )
        if source_object_id is not None:
            statement = statement.where(CanonicalRelationship.source_object_id == source_object_id)
        if target_object_id is not None:
            statement = statement.where(CanonicalRelationship.target_object_id == target_object_id)
        if not include_deleted:
            statement = statement.where(
                CanonicalObject.lifecycle_state != LifecycleState.DELETED.value
            )
        statement = (
            statement.order_by(CanonicalObject.created_at, CanonicalObject.id)
            .offset(offset)
            .limit(limit)
        )
        try:
            objects = list((await self.session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Canonical relationship listing failed.") from exc
        return [CanonicalAggregate(item, await self._get_detail(item)) for item in objects]

    async def has_live_chunk_children(
        self, workspace_id: uuid.UUID, document_object_id: uuid.UUID
    ) -> bool:
        await self.get_workspace(workspace_id)
        statement = (
            select(CanonicalChunk.object_id)
            .join(CanonicalObject, CanonicalObject.id == CanonicalChunk.object_id)
            .where(
                CanonicalObject.workspace_id == workspace_id,
                CanonicalObject.lifecycle_state != LifecycleState.DELETED.value,
                CanonicalChunk.document_object_id == document_object_id,
            )
            .limit(1)
        )
        try:
            return await self.session.scalar(statement) is not None
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Canonical chunk ancestry lookup failed.") from exc

    async def _update_workspace_row(
        self,
        *,
        workspace_id: uuid.UUID,
        expected_version: int,
        values: dict[str, object],
        allow_archived: bool = False,
    ) -> Workspace:
        excluded_states = [LifecycleState.DELETED.value]
        if not allow_archived:
            excluded_states.append(LifecycleState.ARCHIVED.value)
        statement = (
            update(Workspace)
            .where(
                Workspace.id == workspace_id,
                Workspace.version == expected_version,
                Workspace.lifecycle_state.not_in(excluded_states),
            )
            .values(**values, version=expected_version + 1)
            .returning(Workspace)
        )
        try:
            workspace = (await self.session.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Workspace update failed.") from exc
        if workspace is None:
            existing = await self.get_workspace(workspace_id, include_deleted=True)
            if existing.lifecycle_state == LifecycleState.DELETED.value:
                raise CanonicalConflictError("Deleted workspaces cannot be mutated.")
            if existing.lifecycle_state == LifecycleState.ARCHIVED.value:
                raise CanonicalConflictError("Archived workspaces cannot be updated.")
            raise CanonicalConflictError("Workspace version is stale.")
        return workspace

    async def _update_object_row(
        self,
        *,
        workspace_id: uuid.UUID,
        object_id: uuid.UUID,
        expected_version: int,
        values: dict[str, object],
        allow_archived: bool = False,
    ) -> CanonicalObject:
        workspace = await self.get_workspace(workspace_id)
        if workspace.lifecycle_state == LifecycleState.ARCHIVED.value:
            raise CanonicalConflictError("Archived workspaces cannot mutate child objects.")
        excluded_states = [LifecycleState.DELETED.value]
        if not allow_archived:
            excluded_states.append(LifecycleState.ARCHIVED.value)
        statement = (
            update(CanonicalObject)
            .where(
                CanonicalObject.id == object_id,
                CanonicalObject.workspace_id == workspace_id,
                CanonicalObject.version == expected_version,
                CanonicalObject.lifecycle_state.not_in(excluded_states),
            )
            .values(**values, version=expected_version + 1)
            .returning(CanonicalObject)
        )
        try:
            canonical_object = (await self.session.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Canonical object update failed.") from exc
        if canonical_object is None:
            existing = await self.get_object(workspace_id, object_id, include_deleted=True)
            if existing.object.lifecycle_state == LifecycleState.DELETED.value:
                raise CanonicalConflictError("Deleted canonical objects cannot be mutated.")
            if existing.object.lifecycle_state == LifecycleState.ARCHIVED.value:
                raise CanonicalConflictError("Archived canonical objects cannot be updated.")
            raise CanonicalConflictError("Canonical object version is stale.")
        return canonical_object

    async def _get_detail(self, canonical_object: CanonicalObject) -> CanonicalDetail:
        model_by_type = {
            "document": CanonicalDocument,
            "chunk": CanonicalChunk,
            "note": CanonicalNote,
            "execution": CanonicalExecution,
            "relationship": CanonicalRelationship,
        }
        model = model_by_type.get(canonical_object.object_type)
        if model is None:
            raise CanonicalStorageError("Canonical object type is not supported.")
        try:
            detail = await self.session.get(model, canonical_object.id)
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Canonical object detail lookup failed.") from exc
        if detail is None:
            raise CanonicalStorageError("Canonical object detail is missing.")
        return cast(CanonicalDetail, detail)

    async def _raise_object_boundary_or_missing(
        self, workspace_id: uuid.UUID, object_id: uuid.UUID
    ) -> NoReturn:
        try:
            existing_workspace = await self.session.scalar(
                select(CanonicalObject.workspace_id).where(CanonicalObject.id == object_id)
            )
        except SQLAlchemyError as exc:
            raise CanonicalStorageError("Canonical object lookup failed.") from exc
        if existing_workspace is not None and existing_workspace != workspace_id:
            raise WorkspaceBoundaryError("Canonical object not found in this workspace.")
        raise CanonicalNotFoundError("Canonical object not found.")

    async def _flush(self, message: str) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise CanonicalConflictError("Canonical persistence conflict.") from exc
        except SQLAlchemyError as exc:
            raise CanonicalStorageError(message) from exc


__all__ = [
    "CanonicalAggregate",
    "CanonicalDetail",
    "CanonicalRepository",
]
