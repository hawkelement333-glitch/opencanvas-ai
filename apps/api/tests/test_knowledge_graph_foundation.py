from __future__ import annotations

import uuid
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    CanonicalCanvasObjectBinding,
    CanonicalGraphEntity,
    CanonicalGraphRelationship,
    CanonicalObject,
    CanonicalRelationship,
    CanonicalRelationshipHistory,
    CanonicalRelationshipProvenance,
    Canvas,
    DomainEventOutbox,
    DomainEventProvenance,
    DomainEventRecord,
    TraceEvent,
    User,
    WorkspaceGraphState,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import Capability
from opencanvas_api.services.agents.execution import ACTION_REGISTRY, ControlledAction
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalNotFoundError,
    CanonicalStorageError,
    CanonicalValidationError,
)
from opencanvas_api.services.canonical.service import (
    CanonicalService,
    CreateObjectInput,
)
from opencanvas_api.services.domain_events import (
    DomainEventService,
    DomainEventStorageError,
)
from opencanvas_api.services.knowledge_graph import (
    CreateGraphRelationship,
    DeactivateGraphRelationship,
    GraphEntityReference,
    KnowledgeGraphService,
)
from opencanvas_api.services.trace import TracePersistenceError, TraceService


async def _foundation(
    database: Database,
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    async with database.sessions() as session:
        canvas = Canvas(
            id=uuid.uuid4(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            name="Knowledge graph",
        )
        session.add(canvas)
        canonical = CanonicalService(session)
        objects: dict[str, uuid.UUID] = {}
        for key, object_type, payload in (
            (
                "document_one",
                "document",
                {
                    "display_name": "One",
                    "source_type": "upload",
                    "processing_status": "ready",
                },
            ),
            (
                "document_two",
                "document",
                {
                    "display_name": "Two",
                    "source_type": "upload",
                    "processing_status": "ready",
                },
            ),
            ("note_one", "note", {"title": "One", "content": "First"}),
            ("note_two", "note", {"title": "Two", "content": "Second"}),
            (
                "execution",
                "execution",
                {"execution_type": "test", "status": "pending"},
            ),
        ):
            aggregate = await canonical.create_object(
                CreateObjectInput(
                    workspace_id=SYSTEM_WORKSPACE_ID,
                    object_type=cast(Any, object_type),
                    payload=payload,
                    actor_id=str(SYSTEM_USER_ID),
                )
            )
            objects[key] = aggregate.object.id
        await session.commit()
        return canvas.id, objects


def _create(
    canvas_id: uuid.UUID,
    objects: dict[str, uuid.UUID],
    relationship_type: str,
    source_key: str,
    source_kind: str,
    target_key: str,
    target_kind: str,
    key: str,
) -> CreateGraphRelationship:
    return CreateGraphRelationship(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id,
        relationship_type=cast(Any, relationship_type),
        source=GraphEntityReference(
            kind=cast(Any, source_kind),
            object_id=objects[source_key],
        ),
        target=GraphEntityReference(
            kind=cast(Any, target_kind),
            object_id=objects[target_key],
        ),
        idempotency_key=key,
    )


async def test_supported_entities_relationship_registry_direction_and_provenance(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    cases = (
        ("references", "document_one", "document", "note_one", "note"),
        ("derived_from", "note_one", "note", "document_one", "document"),
        ("related_to", "document_two", "document", "execution", "execution"),
        ("cites", "note_two", "note", "document_two", "document"),
        ("supports", "document_one", "document", "note_two", "note"),
        ("contradicts", "note_one", "note", "note_two", "note"),
        ("produced_by", "document_two", "document", "execution", "execution"),
        ("affected_by", "note_two", "note", "execution", "execution"),
    )
    relationship_ids: set[uuid.UUID] = set()
    async with database.sessions() as session:
        graph = KnowledgeGraphService(session)
        for index, case in enumerate(cases):
            created = await graph.create_relationship(
                _create(canvas_id, objects, *case, key=f"registry-{index}")
            )
            assert created.relationship.relationship_type == case[0]
            assert created.source.entity_kind == case[2]
            assert created.target.entity_kind == case[4]
            assert created.relationship.source_object_id == objects[case[1]]
            assert created.relationship.target_object_id == objects[case[3]]
            assert created.provenance.origin_type == "user_created"
            assert created.provenance.actor_user_id == SYSTEM_USER_ID
            assert created.provenance.execution_id is None
            assert len(created.graph.canonical_digest) == 64
            assert len(created.provenance.provenance_digest) == 64
            assert created.current_history.state == "active"
            relationship_ids.add(created.graph.relationship_id)
        await session.commit()

    assert len(relationship_ids) == len(cases)
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalGraphEntity)) == 5
        assert (
            await session.scalar(select(func.count()).select_from(CanonicalCanvasObjectBinding))
            == 5
        )
        state = await session.get(WorkspaceGraphState, SYSTEM_WORKSPACE_ID)
        assert state is not None
        assert state.revision == len(cases)


async def test_exact_duplicate_replays_and_conflicting_idempotency_fails_closed(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    command = _create(
        canvas_id,
        objects,
        "references",
        "document_one",
        "document",
        "note_one",
        "note",
        "stable-key",
    )
    async with database.sessions() as session:
        graph = KnowledgeGraphService(session)
        created = await graph.create_relationship(command)
        await session.commit()
        replayed = await graph.create_relationship(command)
        await session.commit()
        assert replayed.replayed is True
        assert replayed.graph.relationship_id == created.graph.relationship_id
        assert (
            await session.scalar(select(func.count()).select_from(CanonicalGraphRelationship)) == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(CanonicalRelationshipHistory))
            == 1
        )

        conflicting = _create(
            canvas_id,
            objects,
            "references",
            "document_two",
            "document",
            "note_one",
            "note",
            "stable-key",
        )
        with pytest.raises(CanonicalConflictError):
            await graph.create_relationship(conflicting)
        await session.commit()
        assert (
            await session.scalar(select(func.count()).select_from(CanonicalGraphRelationship)) == 1
        )


async def test_invalid_entities_compatibility_self_cycle_and_scope_fail_closed(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    async with database.sessions() as session:
        graph = KnowledgeGraphService(session)
        invalid_kind = _create(
            canvas_id,
            objects,
            "cites",
            "document_one",
            "document",
            "note_one",
            "note",
            "invalid-combination",
        )
        with pytest.raises(CanonicalValidationError):
            await graph.create_relationship(invalid_kind)
        await session.commit()

        missing = CreateGraphRelationship(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            relationship_type="references",
            source=GraphEntityReference(kind="note", object_id=uuid.uuid4()),
            target=GraphEntityReference(kind="note", object_id=objects["note_one"]),
            idempotency_key="missing",
        )
        with pytest.raises(CanonicalNotFoundError):
            await graph.create_relationship(missing)
        await session.commit()

        self_edge = CreateGraphRelationship(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            relationship_type="related_to",
            source=GraphEntityReference(kind="note", object_id=objects["note_one"]),
            target=GraphEntityReference(kind="note", object_id=objects["note_one"]),
            idempotency_key="self",
        )
        with pytest.raises(CanonicalValidationError):
            await graph.create_relationship(self_edge)
        await session.commit()

        first = await graph.create_relationship(
            _create(
                canvas_id,
                objects,
                "derived_from",
                "note_one",
                "note",
                "note_two",
                "note",
                "cycle-one",
            )
        )
        await session.commit()
        assert first.current_history.state == "active"
        with pytest.raises(CanonicalValidationError):
            await graph.create_relationship(
                _create(
                    canvas_id,
                    objects,
                    "derived_from",
                    "note_two",
                    "note",
                    "note_one",
                    "note",
                    "cycle-two",
                )
            )
        await session.commit()

    other_user = User(
        id=uuid.uuid4(),
        email="other@example.test",
        email_normalized="other@example.test",
        password_hash="test",
        display_name="Other",
    )
    async with database.sessions() as session:
        session.add(other_user)
        await session.commit()
        graph = KnowledgeGraphService(session)
        cross_user = _create(
            canvas_id,
            objects,
            "references",
            "document_one",
            "document",
            "note_one",
            "note",
            "cross-user",
        )
        with pytest.raises(CanonicalNotFoundError):
            await graph.create_relationship(
                CreateGraphRelationship(
                    user_id=other_user.id,
                    workspace_id=cross_user.workspace_id,
                    canvas_id=cross_user.canvas_id,
                    relationship_type=cross_user.relationship_type,
                    source=cross_user.source,
                    target=cross_user.target,
                    idempotency_key=cross_user.idempotency_key,
                )
            )
        await session.commit()


async def test_deactivation_is_append_only_and_history_survives_endpoint_delete(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    async with database.sessions() as session:
        graph = KnowledgeGraphService(session)
        created = await graph.create_relationship(
            _create(
                canvas_id,
                objects,
                "supports",
                "document_one",
                "document",
                "note_one",
                "note",
                "create-history",
            )
        )
        await session.commit()
        relationship_id = created.graph.relationship_id
        deactivated = await graph.deactivate_relationship(
            DeactivateGraphRelationship(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                relationship_id=relationship_id,
                expected_version=1,
                idempotency_key="deactivate-history",
                target_state="superseded",
                reason_code="user_replaced",
            )
        )
        await session.commit()
        assert deactivated.object.version == 2
        assert deactivated.object.lifecycle_state == "deleted"
        assert deactivated.current_history.state == "superseded"
        history = await graph.list_history(
            SYSTEM_USER_ID,
            SYSTEM_WORKSPACE_ID,
            canvas_id,
            relationship_id,
        )
        assert [item.state for item in history] == ["active", "superseded"]
        assert history[1].previous_history_id == history[0].history_id

        replay = await graph.deactivate_relationship(
            DeactivateGraphRelationship(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                relationship_id=relationship_id,
                expected_version=1,
                idempotency_key="deactivate-history",
                target_state="superseded",
                reason_code="user_replaced",
            )
        )
        await session.commit()
        assert replay.replayed
        assert (
            await session.scalar(select(func.count()).select_from(CanonicalRelationshipHistory))
            == 2
        )

        with pytest.raises(ValueError, match="append-only"):
            history[0].state = "rejected"
            await session.flush()
        await session.rollback()

        source = await session.get(CanonicalObject, objects["document_one"])
        assert source is not None
        source.lifecycle_state = "deleted"
        source.version += 1
        await session.commit()
        historical = await graph.get_relationship(
            SYSTEM_USER_ID,
            SYSTEM_WORKSPACE_ID,
            canvas_id,
            relationship_id,
        )
        assert historical.current_history.state == "superseded"
        assert historical.provenance.relationship_id == relationship_id


async def test_failure_injection_rolls_back_graph_provenance_history_and_success_trace(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas_id, objects = await _foundation(database)
    async with database.sessions() as session:
        graph = KnowledgeGraphService(session)
        original_flush = graph._flush

        async def fail_after_relationship(message: str) -> None:
            await original_flush(message)
            if message == "Knowledge graph relationship persistence failed.":
                raise CanonicalValidationError("Injected provenance failure.")

        monkeypatch.setattr(graph, "_flush", fail_after_relationship)
        with pytest.raises(CanonicalValidationError):
            await graph.create_relationship(
                _create(
                    canvas_id,
                    objects,
                    "references",
                    "document_one",
                    "document",
                    "note_one",
                    "note",
                    "failure-injection",
                )
            )
        await session.commit()

    async with database.sessions() as session:
        for model in (
            CanonicalRelationship,
            CanonicalGraphRelationship,
            CanonicalRelationshipProvenance,
            CanonicalRelationshipHistory,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        traces = (
            await session.scalars(
                select(TraceEvent).where(
                    TraceEvent.operation == "knowledge_graph.relationship.create"
                )
            )
        ).all()
        assert [trace.status for trace in traces] == ["started", "failed"]
        state = await session.get(WorkspaceGraphState, SYSTEM_WORKSPACE_ID)
        assert state is None


async def test_graph_mutation_event_provenance_and_outbox_commit_once(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    command = _create(
        canvas_id,
        objects,
        "references",
        "document_one",
        "document",
        "note_one",
        "note",
        "event-atomicity",
    )
    async with database.sessions() as session:
        graph = KnowledgeGraphService(session)
        created = await graph.create_relationship(command)
        replayed = await graph.create_relationship(command)
        assert replayed.graph.relationship_id == created.graph.relationship_id
        await session.commit()
        event = await session.scalar(select(DomainEventRecord))
        assert event is not None
        assert event.subject_id == created.graph.relationship_id
        assert event.graph_revision == created.current_history.graph_revision
        assert event.canvas_id == canvas_id
        assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(DomainEventProvenance)) == 1
        assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) == 1


async def test_event_outbox_failure_rolls_back_complete_graph_transaction(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)

    def fail_after_outbox() -> None:
        raise DomainEventStorageError("injected outbox failure")

    async with database.sessions() as session:
        events = DomainEventService(session, after_outbox=fail_after_outbox)
        graph = KnowledgeGraphService(session, event_service=events)
        with pytest.raises(CanonicalStorageError, match="event persistence"):
            await graph.create_relationship(
                _create(
                    canvas_id,
                    objects,
                    "references",
                    "document_one",
                    "document",
                    "note_one",
                    "note",
                    "outbox-atomicity",
                )
            )
        await session.commit()

    async with database.sessions() as session:
        for model in (
            CanonicalGraphRelationship,
            CanonicalRelationshipProvenance,
            CanonicalRelationshipHistory,
            DomainEventRecord,
            DomainEventProvenance,
            DomainEventOutbox,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        traces = (
            await session.scalars(
                select(TraceEvent).where(
                    TraceEvent.operation == "knowledge_graph.relationship.create"
                )
            )
        ).all()
        assert [trace.status for trace in traces] == ["started", "failed"]
        assert await session.get(WorkspaceGraphState, SYSTEM_WORKSPACE_ID) is None


async def test_trace_completion_failure_rolls_back_graph_and_records_failure(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas_id, objects = await _foundation(database)
    async with database.sessions() as session:
        trace_service = TraceService(session)

        async def fail_completion(*_args: object, **_kwargs: object) -> None:
            raise TracePersistenceError("injected completion failure")

        monkeypatch.setattr(trace_service, "complete_trace", fail_completion)
        graph = KnowledgeGraphService(session, trace_service=trace_service)
        with pytest.raises(CanonicalStorageError) as caught:
            await graph.create_relationship(
                _create(
                    canvas_id,
                    objects,
                    "references",
                    "document_one",
                    "document",
                    "note_one",
                    "note",
                    "trace-completion-failure",
                )
            )
        assert "trace completion failed" in str(caught.value).lower()
        await session.commit()

    async with database.sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(CanonicalGraphRelationship)) == 0
        )
        traces = (
            await session.scalars(
                select(TraceEvent).where(
                    TraceEvent.operation == "knowledge_graph.relationship.create"
                )
            )
        ).all()
        assert [trace.status for trace in traces] == ["started", "failed"]


async def test_competing_relationship_creation_has_one_authoritative_edge(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    first = _create(
        canvas_id,
        objects,
        "references",
        "document_one",
        "document",
        "note_one",
        "note",
        "competitor-one",
    )
    second = _create(
        canvas_id,
        objects,
        "references",
        "document_one",
        "document",
        "note_one",
        "note",
        "competitor-two",
    )
    async with database.sessions() as first_session:
        await KnowledgeGraphService(first_session).create_relationship(first)
        await first_session.commit()
    async with database.sessions() as second_session:
        with pytest.raises(CanonicalConflictError):
            await KnowledgeGraphService(second_session).create_relationship(second)
        await second_session.commit()
    async with database.sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(CanonicalGraphRelationship)) == 1
        )


async def test_orm_rejects_history_and_provenance_delete(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    async with database.sessions() as session:
        graph = KnowledgeGraphService(session)
        created = await graph.create_relationship(
            _create(
                canvas_id,
                objects,
                "references",
                "document_one",
                "document",
                "note_one",
                "note",
                "immutable-history",
            )
        )
        await session.commit()
        with pytest.raises(ValueError, match="append-only"):
            await session.delete(created.provenance)
            await session.flush()
        await session.rollback()


def _enable_real_auth(app: FastAPI) -> None:
    current = cast(Settings, app.dependency_overrides[get_settings]())
    app.dependency_overrides[get_settings] = lambda: current.model_copy(
        update={
            "auth_test_bypass": False,
            "session_secret": "test-session-secret-that-is-long-enough-2026",
            "auth_requests_per_ip_per_minute": 100,
        }
    )


async def _signup(
    client: httpx.AsyncClient,
    prefix: str,
    email: str,
) -> dict[str, Any]:
    response = await client.post(
        f"{prefix}/auth/signup",
        json={
            "email": email,
            "password": "Correct-Horse-2026",
            "displayName": "Graph Owner",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


@pytest.mark.security
async def test_graph_api_authentication_csrf_scope_and_authority_fields(
    app: FastAPI,
    api_prefix: str,
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as owner,
        httpx.AsyncClient(transport=transport, base_url="http://test") as stranger,
        httpx.AsyncClient(transport=transport, base_url="http://test") as anonymous,
    ):
        owner_session = await _signup(owner, api_prefix, "graph-owner@example.test")
        headers = {"X-CSRF-Token": cast(str, owner_session["csrfToken"])}
        workspace = cast(
            dict[str, Any],
            (await owner.get(f"{api_prefix}/workspaces")).json()[0],
        )
        workspace_id = workspace["id"]
        canvas_response = await owner.post(
            f"{api_prefix}/canvases",
            json={
                "idempotencyKey": str(uuid.uuid4()),
                "name": "Graph API",
                "workspaceId": workspace_id,
            },
            headers=headers,
        )
        assert canvas_response.status_code == 201, canvas_response.text
        canvas_id = canvas_response.json()["id"]
        notes: list[dict[str, Any]] = []
        for index in range(2):
            response = await owner.post(
                f"{api_prefix}/workspaces/{workspace_id}/notes",
                json={"title": f"Note {index}", "content": f"Content {index}"},
                headers=headers,
            )
            assert response.status_code == 201, response.text
            notes.append(cast(dict[str, Any], response.json()))

        endpoint = (
            f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}/"
            "knowledge-graph/relationships"
        )
        payload = {
            "relationshipType": "contradicts",
            "source": {"kind": "note", "objectId": notes[0]["id"]},
            "target": {"kind": "note", "objectId": notes[1]["id"]},
            "idempotencyKey": "graph-api-create",
        }
        assert (await anonymous.post(endpoint, json=payload)).status_code == 401
        missing = await owner.post(endpoint, json=payload)
        invalid = await owner.post(
            endpoint,
            json=payload,
            headers={"X-CSRF-Token": "invalid"},
        )
        assert missing.status_code == invalid.status_code == 403
        assert missing.json()["code"] == invalid.json()["code"] == "csrf_validation_failed"

        override = await owner.post(
            endpoint,
            json={
                **payload,
                "userId": str(uuid.uuid4()),
                "workspaceId": str(uuid.uuid4()),
                "canvasId": str(uuid.uuid4()),
                "originType": "controlled_agent_approved",
                "actorUserId": str(uuid.uuid4()),
                "executionId": str(uuid.uuid4()),
                "canonicalDigest": "f" * 64,
                "traceId": str(uuid.uuid4()),
                "createdAt": "2026-07-25T00:00:00Z",
                "state": "active",
            },
            headers=headers,
        )
        assert override.status_code == 422

        created = await owner.post(endpoint, json=payload, headers=headers)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["relationshipType"] == "contradicts"
        assert body["source"]["objectId"] == notes[0]["id"]
        assert body["target"]["objectId"] == notes[1]["id"]
        assert body["provenance"]["originType"] == "user_created"
        assert body["provenance"]["executionId"] is None
        assert body["currentState"] == "active"
        assert body["replayed"] is False
        serialized = created.text.lower()
        for private_term in ("password", "sql", "traceback", "grantdigest", "policy"):
            assert private_term not in serialized

        duplicate = await owner.post(endpoint, json=payload, headers=headers)
        assert duplicate.status_code == 201
        assert duplicate.json()["relationshipId"] == body["relationshipId"]
        assert duplicate.json()["replayed"] is True

        entity_list = await owner.get(
            f"{endpoint.rsplit('/relationships', 1)[0]}/entities/{notes[0]['id']}/relationships"
        )
        assert entity_list.status_code == 200
        assert [item["relationshipId"] for item in entity_list.json()] == [body["relationshipId"]]

        transition_endpoint = f"{endpoint}/{body['relationshipId']}/transition"
        transitioned = await owner.post(
            transition_endpoint,
            json={
                "expectedVersion": 1,
                "targetState": "rejected",
                "reasonCode": "user_rejected",
                "idempotencyKey": "graph-api-reject",
            },
            headers=headers,
        )
        assert transitioned.status_code == 200, transitioned.text
        assert transitioned.json()["currentState"] == "rejected"
        history = await owner.get(f"{endpoint}/{body['relationshipId']}/history")
        assert history.status_code == 200
        assert [item["state"] for item in history.json()] == ["active", "rejected"]

        await _signup(stranger, api_prefix, "graph-stranger@example.test")
        cross_scope = await stranger.get(f"{endpoint}/{body['relationshipId']}")
        assert cross_scope.status_code == 404
        assert "sql" not in cross_scope.text.lower()
        assert "traceback" not in cross_scope.text.lower()


def test_controlled_agent_registry_does_not_gain_graph_write_authority() -> None:
    graph_capability = Capability.KNOWLEDGE_GRAPH_RELATIONSHIP_WRITE
    assert all("graph" not in action.value for action in ControlledAction)
    assert set(ACTION_REGISTRY) == {ControlledAction.GENERATE_GROUNDED_DRAFT}
    assert all(
        graph_capability not in boundary.allowed_capabilities
        for boundary in ACTION_REGISTRY.values()
    )
