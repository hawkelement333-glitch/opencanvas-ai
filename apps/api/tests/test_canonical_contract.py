from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

import pytest
from pydantic import JsonValue, ValidationError
from sqlalchemy import select, update

from opencanvas_api.db.models import CanonicalObject
from opencanvas_api.db.session import Database
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalNotFoundError,
    CanonicalValidationError,
    LifecycleState,
)
from opencanvas_api.services.canonical.repository import CanonicalAggregate
from opencanvas_api.services.canonical.service import (
    CanonicalService,
    CreateObjectInput,
    CreateRelationshipInput,
    CreateWorkspaceInput,
    RelationshipQueryFilters,
    TransitionObjectInput,
    TransitionWorkspaceInput,
    UpdateObjectInput,
)


async def _workspace(service: CanonicalService, name: str = "Contract") -> uuid.UUID:
    workspace = await service.create_workspace(CreateWorkspaceInput(name=name))
    return workspace.id


async def _note(
    service: CanonicalService,
    workspace_id: uuid.UUID,
    title: str,
    *,
    metadata: dict[str, JsonValue] | None = None,
) -> CanonicalAggregate:
    return await service.create_object(
        CreateObjectInput(
            workspace_id=workspace_id,
            object_type="note",
            payload={"title": title, "content": f"{title} content"},
            metadata=metadata or {},
        )
    )


async def test_canonical_identity_and_timestamps_survive_mutation(
    database: Database,
) -> None:
    old_updated_at = datetime(2000, 1, 1)
    async with database.sessions() as session:
        service = CanonicalService(session)
        workspace_id = await _workspace(service)
        created = await _note(service, workspace_id, "Stable identity")
        object_id = created.object.id
        created_at = created.object.created_at
        await session.commit()

        with pytest.raises(CanonicalValidationError):
            await service.update_object(
                UpdateObjectInput(
                    workspace_id=workspace_id,
                    object_id=object_id,
                    expected_version=1,
                    payload={"id": str(uuid.uuid4())},
                )
            )
        await session.commit()

        await session.execute(
            update(CanonicalObject)
            .where(CanonicalObject.id == object_id)
            .values(updated_at=old_updated_at)
        )
        await session.commit()

        updated = await service.update_object(
            UpdateObjectInput(
                workspace_id=workspace_id,
                object_id=object_id,
                expected_version=1,
                metadata={"updated": True},
            )
        )
        await session.commit()

    assert updated.object.id == object_id
    assert updated.object.version == 2

    async with database.sessions() as session:
        persisted = await session.scalar(
            select(CanonicalObject).where(CanonicalObject.id == object_id)
        )
    assert persisted is not None
    assert persisted.id == object_id
    assert persisted.created_at == created_at
    assert persisted.updated_at != old_updated_at
    assert persisted.updated_at > old_updated_at


async def test_nested_metadata_is_detached_and_nan_is_rejected(
    database: Database,
) -> None:
    caller_metadata: dict[str, JsonValue] = {
        "nested": {"labels": ["alpha"], "settings": {"enabled": True}}
    }
    async with database.sessions() as session:
        service = CanonicalService(session)
        workspace_id = await _workspace(service)
        input_data = CreateObjectInput(
            workspace_id=workspace_id,
            object_type="note",
            payload={"title": "Detached", "content": "Metadata snapshot"},
            metadata=caller_metadata,
        )
        created = await service.create_object(input_data)

        nested = cast(dict[str, JsonValue], input_data.metadata["nested"])
        labels = cast(list[JsonValue], nested["labels"])
        labels.append("caller mutation")
        caller_nested = cast(dict[str, JsonValue], caller_metadata["nested"])
        caller_settings = cast(dict[str, JsonValue], caller_nested["settings"])
        caller_settings["enabled"] = False
        await session.commit()

    async with database.sessions() as session:
        persisted = await session.get(CanonicalObject, created.object.id)
    assert persisted is not None
    assert persisted.metadata_payload == {
        "nested": {"labels": ["alpha"], "settings": {"enabled": True}}
    }

    with pytest.raises(ValidationError):
        CreateObjectInput(
            workspace_id=workspace_id,
            object_type="note",
            payload={"title": "Unsafe", "content": "NaN"},
            metadata={"score": float("nan")},
        )


async def test_relationship_queries_are_directional_and_invalid_endpoints_fail(
    database: Database,
) -> None:
    async with database.sessions() as session:
        service = CanonicalService(session)
        workspace_id = await _workspace(service)
        source = await _note(service, workspace_id, "Source")
        target = await _note(service, workspace_id, "Target")
        third = await _note(service, workspace_id, "Third")

        source_reference = await service.create_relationship(
            CreateRelationshipInput(
                workspace_id=workspace_id,
                relationship_type="references",
                source_object_id=source.object.id,
                target_object_id=target.object.id,
            )
        )
        third_reference = await service.create_relationship(
            CreateRelationshipInput(
                workspace_id=workspace_id,
                relationship_type="references",
                source_object_id=third.object.id,
                target_object_id=target.object.id,
            )
        )
        related = await service.create_relationship(
            CreateRelationshipInput(
                workspace_id=workspace_id,
                relationship_type="related_to",
                source_object_id=source.object.id,
                target_object_id=third.object.id,
            )
        )

        by_source = await service.list_relationships(
            workspace_id,
            RelationshipQueryFilters(source_object_id=source.object.id),
        )
        by_target = await service.list_relationships(
            workspace_id,
            RelationshipQueryFilters(target_object_id=target.object.id),
        )
        by_type = await service.list_relationships(
            workspace_id,
            RelationshipQueryFilters(relationship_type="references"),
        )

        with pytest.raises(CanonicalNotFoundError):
            await service.create_relationship(
                CreateRelationshipInput(
                    workspace_id=workspace_id,
                    relationship_type="references",
                    source_object_id=uuid.uuid4(),
                    target_object_id=target.object.id,
                )
            )
        with pytest.raises(CanonicalNotFoundError):
            await service.create_relationship(
                CreateRelationshipInput(
                    workspace_id=workspace_id,
                    relationship_type="references",
                    source_object_id=source.object.id,
                    target_object_id=uuid.uuid4(),
                )
            )
        await session.commit()

    assert {item.object.id for item in by_source} == {
        source_reference.object.id,
        related.object.id,
    }
    assert {item.object.id for item in by_target} == {
        source_reference.object.id,
        third_reference.object.id,
    }
    assert {item.object.id for item in by_type} == {
        source_reference.object.id,
        third_reference.object.id,
    }


async def test_archived_workspaces_and_objects_can_transition_to_deleted(
    database: Database,
) -> None:
    async with database.sessions() as session:
        service = CanonicalService(session)
        workspace_id = await _workspace(service, "Object lifecycle")
        note = await _note(service, workspace_id, "Disposable")
        active_note = await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=note.object.id,
                expected_version=1,
                target_state=LifecycleState.ACTIVE,
            )
        )
        archived_note = await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=note.object.id,
                expected_version=active_note.object.version,
                target_state=LifecycleState.ARCHIVED,
            )
        )
        deleted_note = await service.transition_object(
            TransitionObjectInput(
                workspace_id=workspace_id,
                object_id=note.object.id,
                expected_version=archived_note.object.version,
                target_state=LifecycleState.DELETED,
            )
        )

        workspace_to_delete = await _workspace(service, "Workspace lifecycle")
        active_workspace = await service.transition_workspace(
            TransitionWorkspaceInput(
                workspace_id=workspace_to_delete,
                expected_version=1,
                target_state=LifecycleState.ACTIVE,
            )
        )
        archived_workspace = await service.transition_workspace(
            TransitionWorkspaceInput(
                workspace_id=workspace_to_delete,
                expected_version=active_workspace.version,
                target_state=LifecycleState.ARCHIVED,
            )
        )
        deleted_workspace = await service.transition_workspace(
            TransitionWorkspaceInput(
                workspace_id=workspace_to_delete,
                expected_version=archived_workspace.version,
                target_state=LifecycleState.DELETED,
            )
        )
        await session.commit()

    assert deleted_note.object.lifecycle_state == LifecycleState.DELETED.value
    assert deleted_note.object.version == 4
    assert deleted_workspace.lifecycle_state == LifecycleState.DELETED.value
    assert deleted_workspace.version == 4
