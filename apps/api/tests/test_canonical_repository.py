from __future__ import annotations

import uuid

import pytest

from opencanvas_api.db.models import CanonicalChunk, CanonicalDocument, CanonicalNote
from opencanvas_api.db.session import Database
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalNotFoundError,
    CanonicalStorageError,
    LifecycleState,
    WorkspaceBoundaryError,
)
from opencanvas_api.services.canonical.repository import CanonicalRepository


async def _workspace(repository: CanonicalRepository, name: str) -> uuid.UUID:
    workspace_id = uuid.uuid4()
    await repository.create_workspace(
        workspace_id=workspace_id,
        name=name,
        description=None,
        owner_id=None,
        lifecycle_state=LifecycleState.CREATED,
        metadata_payload={},
    )
    return workspace_id


async def test_repository_versions_are_monotonic_and_workspace_isolated(
    database: Database,
) -> None:
    async with database.sessions() as session:
        repository = CanonicalRepository(session)
        first_workspace = await _workspace(repository, "First")
        second_workspace = await _workspace(repository, "Second")
        object_id = uuid.uuid4()
        created = await repository.create_object(
            object_id=object_id,
            workspace_id=first_workspace,
            object_type="note",
            lifecycle_state=LifecycleState.CREATED,
            metadata_payload={"source": "test"},
            detail=CanonicalNote(object_id=object_id, title="Note", content="Body"),
        )
        updated = await repository.update_object_metadata(
            workspace_id=first_workspace,
            object_id=object_id,
            expected_version=1,
            metadata_payload={"source": "updated"},
        )

        assert created.object.version == 2  # The identity map reflects the atomic update.
        assert updated.object.version == 2
        assert updated.object.metadata_payload == {"source": "updated"}
        with pytest.raises(CanonicalConflictError, match="stale"):
            await repository.update_object_metadata(
                workspace_id=first_workspace,
                object_id=object_id,
                expected_version=1,
                metadata_payload={},
            )
        with pytest.raises(WorkspaceBoundaryError):
            await repository.get_object(second_workspace, object_id)


async def test_repository_rejects_mismatched_detail_and_cross_workspace_chunk_parent(
    database: Database,
) -> None:
    async with database.sessions() as session:
        repository = CanonicalRepository(session)
        first_workspace = await _workspace(repository, "Documents")
        second_workspace = await _workspace(repository, "Foreign chunks")
        mismatched_id = uuid.uuid4()
        with pytest.raises(CanonicalStorageError, match="does not match"):
            await repository.create_object(
                object_id=mismatched_id,
                workspace_id=first_workspace,
                object_type="note",
                lifecycle_state=LifecycleState.CREATED,
                metadata_payload={},
                detail=CanonicalDocument(
                    object_id=mismatched_id,
                    display_name="Wrong detail",
                    source_type="test",
                    processing_status="created",
                    source_metadata={},
                ),
            )

        document_id = uuid.uuid4()
        await repository.create_object(
            object_id=document_id,
            workspace_id=first_workspace,
            object_type="document",
            lifecycle_state=LifecycleState.CREATED,
            metadata_payload={},
            detail=CanonicalDocument(
                object_id=document_id,
                display_name="Source",
                source_type="test",
                processing_status="ready",
                source_metadata={},
            ),
        )
        chunk_id = uuid.uuid4()
        with pytest.raises(WorkspaceBoundaryError):
            await repository.create_object(
                object_id=chunk_id,
                workspace_id=second_workspace,
                object_type="chunk",
                lifecycle_state=LifecycleState.CREATED,
                metadata_payload={},
                detail=CanonicalChunk(
                    object_id=chunk_id,
                    document_object_id=document_id,
                    ordered_position=0,
                    content="A foreign chunk",
                    source_location={},
                ),
            )


async def test_deleted_workspace_hides_children_but_include_deleted_remains_audit_read(
    database: Database,
) -> None:
    async with database.sessions() as session:
        repository = CanonicalRepository(session)
        workspace_id = await _workspace(repository, "Disposable")
        note_id = uuid.uuid4()
        await repository.create_object(
            object_id=note_id,
            workspace_id=workspace_id,
            object_type="note",
            lifecycle_state=LifecycleState.CREATED,
            metadata_payload={},
            detail=CanonicalNote(object_id=note_id, title="Hidden", content="Audit content"),
        )
        await repository.transition_workspace(
            workspace_id=workspace_id,
            expected_version=1,
            target_state=LifecycleState.DELETED,
        )

        with pytest.raises(CanonicalNotFoundError, match="Workspace not found"):
            await repository.get_object(workspace_id, note_id)
        audit_copy = await repository.get_object(workspace_id, note_id, include_deleted=True)
        assert audit_copy.object.id == note_id
        with pytest.raises(CanonicalNotFoundError, match="Workspace not found"):
            await repository.update_object_metadata(
                workspace_id=workspace_id,
                object_id=note_id,
                expected_version=1,
                metadata_payload={"forbidden": True},
            )


async def test_archived_records_reject_updates_but_can_be_reactivated(
    database: Database,
) -> None:
    async with database.sessions() as session:
        repository = CanonicalRepository(session)
        workspace_id = await _workspace(repository, "Archive lifecycle")
        active_workspace = await repository.transition_workspace(
            workspace_id=workspace_id,
            expected_version=1,
            target_state=LifecycleState.ACTIVE,
        )
        archived_workspace = await repository.transition_workspace(
            workspace_id=workspace_id,
            expected_version=active_workspace.version,
            target_state=LifecycleState.ARCHIVED,
        )
        with pytest.raises(CanonicalConflictError, match="Archived"):
            await repository.update_workspace(
                workspace_id=workspace_id,
                expected_version=archived_workspace.version,
                name="Forbidden update",
                description=None,
                owner_id=None,
                metadata_payload={},
            )
        reactivated_workspace = await repository.transition_workspace(
            workspace_id=workspace_id,
            expected_version=archived_workspace.version,
            target_state=LifecycleState.ACTIVE,
        )
        assert reactivated_workspace.version == 4

        note_id = uuid.uuid4()
        note = await repository.create_object(
            object_id=note_id,
            workspace_id=workspace_id,
            object_type="note",
            lifecycle_state=LifecycleState.CREATED,
            metadata_payload={},
            detail=CanonicalNote(object_id=note_id, title="Archive", content="Lifecycle"),
        )
        note = await repository.transition_object(
            workspace_id=workspace_id,
            object_id=note_id,
            expected_version=note.object.version,
            target_state=LifecycleState.ACTIVE,
        )
        note = await repository.transition_object(
            workspace_id=workspace_id,
            object_id=note_id,
            expected_version=note.object.version,
            target_state=LifecycleState.ARCHIVED,
        )
        with pytest.raises(CanonicalConflictError, match="Archived"):
            await repository.update_object_metadata(
                workspace_id=workspace_id,
                object_id=note_id,
                expected_version=note.object.version,
                metadata_payload={"forbidden": True},
            )
        reactivated_note = await repository.transition_object(
            workspace_id=workspace_id,
            object_id=note_id,
            expected_version=note.object.version,
            target_state=LifecycleState.ACTIVE,
        )
        assert reactivated_note.object.version == 4
