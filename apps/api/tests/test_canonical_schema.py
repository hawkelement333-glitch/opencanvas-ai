from __future__ import annotations

import uuid

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect
from sqlalchemy.exc import IntegrityError

from opencanvas_api.db.models import (
    CanonicalChunk,
    CanonicalDocument,
    CanonicalExecution,
    CanonicalNote,
    CanonicalObject,
    CanonicalRelationship,
    Workspace,
)
from opencanvas_api.db.session import Database


def _foreign_key_contract(
    model: type[object],
) -> set[tuple[tuple[str, ...], tuple[str, ...], str | None]]:
    table = inspect(model).local_table
    return {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _unique_contract(model: type[object]) -> set[tuple[str, ...]]:
    table = inspect(model).local_table
    return {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _checks(model: type[object]) -> str:
    table = inspect(model).local_table
    return " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_workspace_schema_and_legacy_canvas_link() -> None:
    table = inspect(Workspace).local_table
    assert table.name == "workspaces"
    assert Workspace.metadata_payload.property.columns[0].name == "metadata"
    assert _foreign_key_contract(Workspace) == {
        (("legacy_canvas_id",), ("canvases.id",), "SET NULL")
    }
    assert ("legacy_canvas_id",) in _unique_contract(Workspace)
    assert table.c.owner_id.nullable is True
    assert table.c.legacy_canvas_id.nullable is True
    checks = _checks(Workspace)
    assert "version >= 1" in checks
    assert all(state in checks for state in ("created", "active", "archived", "deleted"))


def test_canonical_object_schema_is_workspace_scoped() -> None:
    table = inspect(CanonicalObject).local_table
    assert table.name == "canonical_objects"
    assert CanonicalObject.metadata_payload.property.columns[0].name == "metadata"
    assert _foreign_key_contract(CanonicalObject) == {
        (("workspace_id",), ("workspaces.id",), "RESTRICT")
    }
    assert ("id", "workspace_id") in _unique_contract(CanonicalObject)
    checks = _checks(CanonicalObject)
    assert all(
        object_type in checks
        for object_type in ("document", "chunk", "note", "execution", "relationship")
    )
    assert all(state in checks for state in ("created", "active", "archived", "deleted"))
    assert "version >= 1" in checks


def test_canonical_document_chunk_and_note_subtypes() -> None:
    assert _foreign_key_contract(CanonicalDocument) == {
        (("object_id",), ("canonical_objects.id",), "CASCADE"),
        (("legacy_document_id",), ("documents.id",), "SET NULL"),
    }
    assert ("legacy_document_id",) in _unique_contract(CanonicalDocument)
    assert all(
        status in _checks(CanonicalDocument)
        for status in ("created", "processing", "ready", "failed")
    )

    assert _foreign_key_contract(CanonicalChunk) == {
        (("object_id",), ("canonical_objects.id",), "CASCADE"),
        (("document_object_id",), ("canonical_documents.object_id",), "RESTRICT"),
    }
    assert _unique_contract(CanonicalChunk) == {("document_object_id", "ordered_position")}
    assert "ordered_position >= 0" in _checks(CanonicalChunk)

    assert _foreign_key_contract(CanonicalNote) == {
        (("object_id",), ("canonical_objects.id",), "CASCADE")
    }


def test_canonical_execution_schema_and_trace_correlation() -> None:
    table = inspect(CanonicalExecution).local_table
    assert _foreign_key_contract(CanonicalExecution) == {
        (("object_id",), ("canonical_objects.id",), "CASCADE")
    }
    assert table.c.trace_id.nullable is True
    assert table.c.failure.nullable is True
    checks = _checks(CanonicalExecution)
    assert all(
        status in checks for status in ("pending", "running", "succeeded", "failed", "cancelled")
    )
    assert "completed_at >= started_at" in checks


def test_canonical_relationships_enforce_same_workspace_directionally() -> None:
    table = inspect(CanonicalRelationship).local_table
    assert table.c.trace_id.nullable is False
    assert _foreign_key_contract(CanonicalRelationship) == {
        (
            ("object_id", "workspace_id"),
            ("canonical_objects.id", "canonical_objects.workspace_id"),
            "CASCADE",
        ),
        (
            ("source_object_id", "workspace_id"),
            ("canonical_objects.id", "canonical_objects.workspace_id"),
            "RESTRICT",
        ),
        (
            ("target_object_id", "workspace_id"),
            ("canonical_objects.id", "canonical_objects.workspace_id"),
            "RESTRICT",
        ),
    }
    assert _unique_contract(CanonicalRelationship) == {
        ("workspace_id", "source_object_id", "target_object_id", "relationship_type")
    }
    checks = _checks(CanonicalRelationship)
    assert all(
        relationship_type in checks
        for relationship_type in ("contains", "part_of", "references", "derived_from", "related_to")
    )
    assert "source_object_id <> target_object_id" in checks


async def test_cross_workspace_relationship_is_rejected_by_the_database(
    database: Database,
) -> None:
    workspace_one = Workspace(id=uuid.uuid4(), name="One")
    workspace_two = Workspace(id=uuid.uuid4(), name="Two")
    source = CanonicalObject(id=uuid.uuid4(), workspace_id=workspace_one.id, object_type="note")
    target = CanonicalObject(id=uuid.uuid4(), workspace_id=workspace_two.id, object_type="note")
    relationship_object = CanonicalObject(
        id=uuid.uuid4(),
        workspace_id=workspace_one.id,
        object_type="relationship",
    )
    async with database.sessions() as session:
        session.add_all([workspace_one, workspace_two])
        await session.flush()
        session.add_all([source, target, relationship_object])
        await session.commit()
        session.add(
            CanonicalRelationship(
                object_id=relationship_object.id,
                workspace_id=workspace_one.id,
                source_object_id=source.id,
                target_object_id=target.id,
                relationship_type="references",
                trace_id=uuid.uuid4(),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
