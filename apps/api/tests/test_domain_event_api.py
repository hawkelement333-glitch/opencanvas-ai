from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Canvas,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService


@pytest.mark.anyio
async def test_event_detail_delivery_and_activity_are_scoped_and_allowlisted(
    database: Database,
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    canvas_id = uuid.uuid4()
    relationship_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(Canvas(id=canvas_id, workspace_id=SYSTEM_WORKSPACE_ID, name="Activity"))
        await session.flush()
        record = await DomainEventService(session).record(
            CreateDomainEvent(
                event_type="graph.relationship.created",
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                subject_id=relationship_id,
                related_id=uuid.uuid4(),
                actor_user_id=SYSTEM_USER_ID,
                source_identity="api-event",
                trace_id=uuid.uuid4(),
                payload={
                    "relationshipType": "references",
                    "state": "active",
                    "graphRevision": 1,
                },
                origin_type="authenticated_user",
                graph_revision=1,
                graph_relationship_id=relationship_id,
                occurred_at=datetime(2026, 7, 25, 18, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    detail = await client.get(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/events/{record.event.event_id}"
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["eventId"] == str(record.event.event_id)
    assert body["eventType"] == "graph.relationship.created"
    assert body["delivery"]["status"] == "pending_delivery"
    assert body["provenance"]["graphRelationshipId"] == str(relationship_id)
    serialized = str(body)
    for forbidden in (
        "sourceIdentity",
        "requestDigest",
        "leaseOwner",
        "leaseGeneration",
        "worker",
        "grant",
        "policy",
        "secret",
    ):
        assert forbidden not in serialized

    delivery = await client.get(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/events/{record.event.event_id}/delivery"
    )
    assert delivery.status_code == 200
    assert delivery.json() == {
        "status": "pending_delivery",
        "attemptCount": 0,
        "maxAttempts": 3,
        "eligibleAt": "2026-07-25T18:00:00Z",
        "failureClassification": None,
        "completedAt": None,
        "terminalAt": None,
    }

    activity = await client.get(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/activity",
        params={"canvasId": str(canvas_id), "limit": 10},
    )
    assert activity.status_code == 200
    assert [item["eventId"] for item in activity.json()] == [str(record.event.event_id)]
    assert activity.json()[0]["projected"] is False

    relationship_activity = await client.get(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/knowledge-graph/"
        f"relationships/{relationship_id}/activity"
    )
    assert relationship_activity.status_code == 200
    assert len(relationship_activity.json()) == 1

    missing = await client.get(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/events/{uuid.uuid4()}"
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "domain_event_not_found"

    no_dispatch_endpoint = await client.post(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/events/claim"
    )
    assert no_dispatch_endpoint.status_code in {404, 405}


@pytest.mark.anyio
async def test_cross_workspace_event_reads_fail_closed(
    database: Database,
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    other_user_id = uuid.uuid4()
    other_workspace_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(
            User(
                id=other_user_id,
                email="other-events@example.test",
                email_normalized="other-events@example.test",
                password_hash="test-only",
                display_name="Other",
                email_verified=True,
            )
        )
        session.add(
            Workspace(
                id=other_workspace_id,
                owner_id=other_user_id,
                name="Other events",
            )
        )
        await session.commit()

    response = await client.get(f"{api_prefix}/workspaces/{other_workspace_id}/activity")
    assert response.status_code == 404
    assert response.json() == {
        "code": "workspace_not_found",
        "detail": "Workspace not found.",
    }
