from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import get_canonical_service, get_session
from opencanvas_api.db.models import TraceEvent
from opencanvas_api.services.canonical.service import CanonicalService
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    TracePersistenceError,
    TraceService,
)


class _FailCompletionTraceService(TraceService):
    async def complete_trace(self, input_data: CompleteTraceInput) -> TraceEvent:
        del input_data
        raise TracePersistenceError("injected completion failure")


def _json(response: httpx.Response, expected_status: int = 200) -> dict[str, Any]:
    assert response.status_code == expected_status, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def _json_list(response: httpx.Response) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    assert all(isinstance(item, dict) for item in payload)
    return payload


async def test_canonical_api_builds_and_traces_workspace_graph(
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    actor_id = "canonical-api-test"
    workspace = _json(
        await client.post(
            f"{api_prefix}/workspaces",
            json={
                "name": "Research workspace",
                "description": "Canonical graph contract",
                "metadata": {"phase": 2},
                "actorId": actor_id,
            },
        ),
        201,
    )
    workspace_id = workspace["id"]
    assert workspace["version"] == 1
    assert workspace["lifecycleState"] == "created"
    assert "lifecycle_state" not in workspace

    listed_workspaces = _json_list(
        await client.get(
            f"{api_prefix}/workspaces",
            params={"lifecycleState": "created"},
        )
    )
    assert [item["id"] for item in listed_workspaces] == [workspace_id]

    workspace = _json(
        await client.patch(
            f"{api_prefix}/workspaces/{workspace_id}",
            json={
                "expectedVersion": 1,
                "name": "Research knowledge graph",
                "metadata": {"phase": 2, "canonical": True},
                "actorId": actor_id,
            },
        )
    )
    assert workspace["version"] == 2
    workspace = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/transition",
            json={
                "expectedVersion": 2,
                "targetState": "active",
                "actorId": actor_id,
            },
        )
    )
    assert workspace["version"] == 3
    assert workspace["lifecycleState"] == "active"
    assert _json(await client.get(f"{api_prefix}/workspaces/{workspace_id}"))["name"] == (
        "Research knowledge graph"
    )

    document = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/documents",
            json={
                "displayName": "Vox research brief",
                "sourceType": "application/pdf",
                "processingStatus": "processing",
                "sourceMetadata": {"fileName": "vox.pdf", "pageCount": 2},
                "metadata": {"topic": "Project Vox"},
                "actorId": actor_id,
            },
        ),
        201,
    )
    document_id = document["id"]
    assert document["objectType"] == "document"
    assert document["version"] == 1
    document = _json(
        await client.patch(
            f"{api_prefix}/workspaces/{workspace_id}/documents/{document_id}",
            json={
                "expectedVersion": 1,
                "displayName": "Project Vox research brief",
                "processingStatus": "ready",
                "sourceMetadata": {"fileName": "vox.pdf", "pageCount": 2},
                "actorId": actor_id,
            },
        )
    )
    assert document["version"] == 2
    document = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/documents/{document_id}/transition",
            json={
                "expectedVersion": 2,
                "targetState": "active",
                "actorId": actor_id,
            },
        )
    )
    assert document["lifecycleState"] == "active"
    assert document["version"] == 3
    assert (
        _json(await client.get(f"{api_prefix}/workspaces/{workspace_id}/documents/{document_id}"))[
            "processingStatus"
        ]
        == "ready"
    )
    assert [
        item["id"]
        for item in _json_list(
            await client.get(
                f"{api_prefix}/workspaces/{workspace_id}/documents",
                params={"lifecycleState": "active"},
            )
        )
    ] == [document_id]

    chunks: list[dict[str, Any]] = []
    for position, (content, source_location) in enumerate(
        (
            (
                "Project Vox launches in October.",
                {"page": 1, "heading": "Launch plan", "startOffset": 0},
            ),
            (
                "The approved launch budget is $50,000.",
                {"page": 2, "heading": "Budget", "startOffset": 34},
            ),
        )
    ):
        chunks.append(
            _json(
                await client.post(
                    f"{api_prefix}/workspaces/{workspace_id}/chunks",
                    json={
                        "documentObjectId": document_id,
                        "orderedPosition": position,
                        "content": content,
                        "sourceLocation": source_location,
                        "actorId": actor_id,
                    },
                ),
                201,
            )
        )
    first_chunk_id = chunks[0]["id"]
    second_chunk_id = chunks[1]["id"]
    first_chunk = _json(
        await client.patch(
            f"{api_prefix}/workspaces/{workspace_id}/chunks/{first_chunk_id}",
            json={
                "expectedVersion": 1,
                "content": "Project Vox launches on October 15.",
                "actorId": actor_id,
            },
        )
    )
    assert first_chunk["version"] == 2
    first_chunk = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/chunks/{first_chunk_id}/transition",
            json={
                "expectedVersion": 2,
                "targetState": "active",
                "actorId": actor_id,
            },
        )
    )
    assert first_chunk["lifecycleState"] == "active"
    assert _json(
        await client.get(f"{api_prefix}/workspaces/{workspace_id}/chunks/{first_chunk_id}")
    )["content"].endswith("October 15.")
    assert {
        item["id"]
        for item in _json_list(await client.get(f"{api_prefix}/workspaces/{workspace_id}/chunks"))
    } == {first_chunk_id, second_chunk_id}

    note = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/notes",
            json={
                "title": "Launch question",
                "content": "When does Project Vox launch?",
                "metadata": {"selected": True},
                "actorId": actor_id,
            },
        ),
        201,
    )
    note_id = note["id"]
    note = _json(
        await client.patch(
            f"{api_prefix}/workspaces/{workspace_id}/notes/{note_id}",
            json={
                "expectedVersion": 1,
                "title": "Project Vox launch question",
                "actorId": actor_id,
            },
        )
    )
    assert note["version"] == 2
    note = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/notes/{note_id}/transition",
            json={
                "expectedVersion": 2,
                "targetState": "active",
                "actorId": actor_id,
            },
        )
    )
    assert note["lifecycleState"] == "active"
    assert (
        _json(await client.get(f"{api_prefix}/workspaces/{workspace_id}/notes/{note_id}"))["title"]
        == "Project Vox launch question"
    )
    assert [
        item["id"]
        for item in _json_list(await client.get(f"{api_prefix}/workspaces/{workspace_id}/notes"))
    ] == [note_id]

    started_at = datetime.now(UTC)
    execution = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/executions",
            json={
                "executionType": "grounded_answer",
                "status": "pending",
                "inputsMetadata": {
                    "instruction": "Answer the launch question",
                    "selectedObjectIds": [note_id, document_id],
                },
                "actorId": actor_id,
            },
        ),
        201,
    )
    execution_id = execution["id"]
    assert execution["traceId"] is not None
    execution = _json(
        await client.patch(
            f"{api_prefix}/workspaces/{workspace_id}/executions/{execution_id}",
            json={
                "expectedVersion": 1,
                "status": "running",
                "startedAt": started_at.isoformat(),
                "actorId": actor_id,
            },
        )
    )
    assert execution["status"] == "running"
    execution = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/executions/{execution_id}/transition",
            json={
                "expectedVersion": 2,
                "targetState": "active",
                "actorId": actor_id,
            },
        )
    )
    assert execution["version"] == 3
    assert (
        _json(
            await client.get(f"{api_prefix}/workspaces/{workspace_id}/executions/{execution_id}")
        )["status"]
        == "running"
    )
    assert [
        item["id"]
        for item in _json_list(
            await client.get(f"{api_prefix}/workspaces/{workspace_id}/executions")
        )
    ] == [execution_id]

    relationships: list[dict[str, Any]] = []
    for relationship_type, source_id, target_id in (
        ("contains", document_id, first_chunk_id),
        ("contains", document_id, second_chunk_id),
        ("references", note_id, document_id),
        ("related_to", note_id, execution_id),
    ):
        relationships.append(
            _json(
                await client.post(
                    f"{api_prefix}/workspaces/{workspace_id}/relationships",
                    json={
                        "relationshipType": relationship_type,
                        "sourceObjectId": source_id,
                        "targetObjectId": target_id,
                        "actorId": actor_id,
                    },
                ),
                201,
            )
        )

    contains = _json_list(
        await client.get(
            f"{api_prefix}/workspaces/{workspace_id}/relationships",
            params={
                "relationshipType": "contains",
                "sourceId": document_id,
            },
        )
    )
    assert {item["targetObjectId"] for item in contains} == {
        first_chunk_id,
        second_chunk_id,
    }
    references = _json_list(
        await client.get(
            f"{api_prefix}/workspaces/{workspace_id}/relationships",
            params={"targetId": document_id, "relationshipType": "references"},
        )
    )
    assert [item["sourceObjectId"] for item in references] == [note_id]

    removed = relationships[-1]
    response = await client.delete(
        f"{api_prefix}/workspaces/{workspace_id}/relationships/{removed['id']}",
        params={"expectedVersion": 1, "actorId": actor_id},
    )
    assert response.status_code == 204, response.text
    assert (
        _json_list(
            await client.get(
                f"{api_prefix}/workspaces/{workspace_id}/relationships",
                params={"relationshipType": "related_to"},
            )
        )
        == []
    )
    deleted_relationships = _json_list(
        await client.get(
            f"{api_prefix}/workspaces/{workspace_id}/relationships",
            params={
                "relationshipType": "related_to",
                "includeDeleted": "true",
            },
        )
    )
    assert deleted_relationships[0]["lifecycleState"] == "deleted"
    assert deleted_relationships[0]["version"] == 2

    trace_events = _json_list(
        await client.get(
            f"{api_prefix}/trace-events",
            params={"workspaceId": workspace_id, "limit": 500},
        )
    )
    assert [event["timestamp"] for event in trace_events] == sorted(
        event["timestamp"] for event in trace_events
    )
    assert {event["operation"] for event in trace_events} >= {
        "canonical.workspace.create",
        "canonical.workspace.update",
        "canonical.workspace.transition",
        "canonical.object.create",
        "canonical.object.update",
        "canonical.object.transition",
        "canonical.relationship.create",
        "canonical.relationship.remove",
    }
    traces: dict[str, list[dict[str, Any]]] = {}
    for event in trace_events:
        traces.setdefault(event["traceId"], []).append(event)
    assert all(
        [event["status"] for event in events] == ["started", "succeeded"]
        for events in traces.values()
    )
    one_trace = _json_list(await client.get(f"{api_prefix}/traces/{trace_events[0]['traceId']}"))
    assert [event["status"] for event in one_trace] == ["started", "succeeded"]


async def test_canonical_api_persists_failed_trace_without_domain_mutation(
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    workspace_a = _json(
        await client.post(
            f"{api_prefix}/workspaces",
            json={"name": "Workspace A", "actorId": "failure-test"},
        ),
        201,
    )
    workspace_b = _json(
        await client.post(
            f"{api_prefix}/workspaces",
            json={"name": "Workspace B", "actorId": "failure-test"},
        ),
        201,
    )
    document = _json(
        await client.post(
            f"{api_prefix}/workspaces/{workspace_a['id']}/documents",
            json={
                "displayName": "Boundary document",
                "sourceType": "text/plain",
                "actorId": "failure-test",
            },
        ),
        201,
    )

    invalid_transition = await client.post(
        f"{api_prefix}/workspaces/{workspace_a['id']}/documents/{document['id']}/transition",
        json={
            "expectedVersion": 1,
            "targetState": "archived",
            "actorId": "failure-test",
        },
    )
    assert invalid_transition.status_code == 409
    assert invalid_transition.json()["code"] == "invalid_lifecycle_transition"

    cross_workspace_update = await client.patch(
        f"{api_prefix}/workspaces/{workspace_b['id']}/documents/{document['id']}",
        json={
            "expectedVersion": 1,
            "displayName": "Cross-workspace mutation",
            "actorId": "failure-test",
        },
    )
    assert cross_workspace_update.status_code == 404
    assert cross_workspace_update.json()["code"] == "canonical_not_found"

    unchanged = _json(
        await client.get(f"{api_prefix}/workspaces/{workspace_a['id']}/documents/{document['id']}")
    )
    assert unchanged["displayName"] == "Boundary document"
    assert unchanged["lifecycleState"] == "created"
    assert unchanged["version"] == 1

    workspace_a_failures = _json_list(
        await client.get(
            f"{api_prefix}/trace-events",
            params={"workspaceId": workspace_a["id"], "status": "failed"},
        )
    )
    assert len(workspace_a_failures) == 1
    lifecycle_failure = workspace_a_failures[0]
    assert lifecycle_failure["eventType"] == "canonical.object.transition.failed"
    assert lifecycle_failure["error"]["code"] == "invalid_lifecycle_transition"
    assert lifecycle_failure["objectId"] == document["id"]
    lifecycle_trace = _json_list(
        await client.get(f"{api_prefix}/traces/{lifecycle_failure['traceId']}")
    )
    assert [event["status"] for event in lifecycle_trace] == ["started", "failed"]

    workspace_b_failures = _json_list(
        await client.get(
            f"{api_prefix}/trace-events",
            params={"workspaceId": workspace_b["id"], "status": "failed"},
        )
    )
    assert len(workspace_b_failures) == 1
    boundary_failure = workspace_b_failures[0]
    assert boundary_failure["eventType"] == "canonical.object.update.failed"
    assert boundary_failure["error"]["code"] == "canonical_not_found"
    boundary_trace = _json_list(
        await client.get(f"{api_prefix}/traces/{boundary_failure['traceId']}")
    )
    assert [event["status"] for event in boundary_trace] == ["started", "failed"]


async def test_canonical_api_trace_completion_failure_is_atomic(
    app: FastAPI,
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    workspace = _json(
        await client.post(
            f"{api_prefix}/workspaces",
            json={"name": "Atomic workspace", "actorId": "atomicity-test"},
        ),
        201,
    )

    def failing_service(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> CanonicalService:
        return CanonicalService(
            session,
            trace_service=_FailCompletionTraceService(session),
        )

    app.dependency_overrides[get_canonical_service] = failing_service
    try:
        response = await client.post(
            f"{api_prefix}/workspaces/{workspace['id']}/notes",
            json={
                "title": "Must roll back",
                "content": "This canonical note must never become durable.",
                "actorId": "atomicity-test",
            },
        )
    finally:
        app.dependency_overrides.pop(get_canonical_service, None)

    assert response.status_code == 503
    assert response.json() == {
        "code": "canonical_storage_failed",
        "detail": "Canonical trace completion failed.",
    }
    assert _json_list(await client.get(f"{api_prefix}/workspaces/{workspace['id']}/notes")) == []

    failures = _json_list(
        await client.get(
            f"{api_prefix}/trace-events",
            params={"workspaceId": workspace["id"], "status": "failed"},
        )
    )
    assert len(failures) == 1
    failure = failures[0]
    assert failure["eventType"] == "canonical.object.create.failed"
    assert failure["error"]["code"] == "canonical_storage_failed"
    assert failure["error"]["message"] == "Canonical trace completion failed."
    operation_trace = _json_list(await client.get(f"{api_prefix}/traces/{failure['traceId']}"))
    assert [event["status"] for event in operation_trace] == ["started", "failed"]
    assert not any(event["status"] == "succeeded" for event in operation_trace)
