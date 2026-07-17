from __future__ import annotations

from sqlalchemy import UniqueConstraint, inspect

from opencanvas_api.db.models import (
    AIExecutionCitation,
    AIExecutionSource,
    AIResponse,
)


def test_ai_response_node_is_optional_and_uses_set_null() -> None:
    node_column = AIResponse.__table__.c.node_id
    assert node_column.nullable is True
    node_foreign_key = next(iter(node_column.foreign_keys))
    assert node_foreign_key.ondelete == "SET NULL"


def test_execution_citations_only_reference_the_request() -> None:
    mapper = inspect(AIExecutionCitation)
    assert mapper.local_table.name == "ai_execution_citations"
    foreign_keys = {
        (foreign_key.parent.name, foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in mapper.local_table.foreign_keys
    }
    assert foreign_keys == {("request_id", "ai_requests.id", "CASCADE")}
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in mapper.local_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_columns == {("request_id", "ordinal")}
    assert {
        "ai_response_id_snapshot",
        "document_id_snapshot",
        "chunk_id_snapshot",
        "document_name_snapshot",
        "page_number_snapshot",
        "heading_snapshot",
        "char_start_snapshot",
        "char_end_snapshot",
    } <= set(mapper.local_table.c.keys())


def test_execution_sources_only_reference_the_request() -> None:
    mapper = inspect(AIExecutionSource)
    assert mapper.local_table.name == "ai_execution_sources"
    foreign_keys = {
        (foreign_key.parent.name, foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in mapper.local_table.foreign_keys
    }
    assert foreign_keys == {("request_id", "ai_requests.id", "CASCADE")}
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in mapper.local_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_columns == {("request_id", "document_id_snapshot", "document_node_id_snapshot")}
    assert mapper.local_table.c.document_node_id_snapshot.nullable is False
    assert {
        "response_node_id_snapshot",
        "document_id_snapshot",
        "document_node_id_snapshot",
        "document_name_snapshot",
        "max_relevance_score",
    } <= set(mapper.local_table.c.keys())
