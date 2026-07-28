from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import func, select, update

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    Canvas,
    CollaborationAuditEvent,
    CollaborationResource,
    CollaborationResourceOwnershipTransition,
    Document,
    DomainEventRecord,
    IndexerAuditEvent,
    IndexerFailure,
    IndexPublication,
    IndexRevision,
    IndexRevisionChunk,
    IngestionRequest,
    IngestionRequestTransition,
    NormalizedArtifact,
    RetrievalHead,
    TraceEvent,
    VectorMaterialization,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services import indexer as indexer_module
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.documents import (
    DocumentProcessingError,
    build_document_storage,
    build_embedding_provider,
    delete_document,
)
from opencanvas_api.services.indexer import (
    IndexerError,
    IndexerHooks,
    IngestionService,
    process_ingestion_request,
)
from tests.test_canvas_api import _create_canvas

JsonObject = dict[str, Any]


async def _register_canvas_resource(
    database: Database, *, workspace_id: uuid.UUID, canvas_id: uuid.UUID
) -> None:
    async with database.sessions() as session:
        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == SYSTEM_USER_ID,
            )
        )
        authority = await session.get(WorkspaceAuthorityVersion, workspace_id)
        assert membership is not None and authority is not None
        now = datetime.now(UTC)
        session.add(
            CollaborationResource(
                resource_id=canvas_id,
                workspace_id=workspace_id,
                resource_kind="canvas",
                canvas_id=canvas_id,
                canonical_object_id=None,
                workflow_definition_id=None,
                agent_id=None,
                target_user_id=None,
                creator_user_id=SYSTEM_USER_ID,
                creation_trace_id=uuid.uuid4(),
                created_at=now,
            )
        )
        session.add(
            CollaborationResourceOwnershipTransition(
                transition_id=uuid.uuid5(canvas_id, "indexer-test-canvas-owner"),
                resource_id=canvas_id,
                workspace_id=workspace_id,
                resource_kind="canvas",
                sequence=0,
                previous_owner_kind=None,
                previous_owner_membership_id=None,
                previous_owner_user_id=None,
                current_owner_kind="workspace",
                current_owner_membership_id=None,
                current_owner_user_id=None,
                visibility_policy="private",
                authority_generation=authority.authority_generation,
                actor_user_id=SYSTEM_USER_ID,
                actor_membership_id=membership.membership_id,
                reason_code="test_resource_registration",
                trace_id=uuid.uuid4(),
                audit_event_id=None,
                recorded_at=now,
            )
        )
        await session.commit()


async def _create_isolated_workspace_canvas(
    database: Database, *, name: str
) -> tuple[uuid.UUID, uuid.UUID]:
    workspace_id = uuid.uuid4()
    canvas_id = uuid.uuid4()
    membership_id = uuid.uuid5(workspace_id, "owner-membership")
    trace_id = uuid.uuid5(membership_id, "bootstrap-trace")
    audit_id = uuid.uuid5(membership_id, "bootstrap-audit")
    now = datetime.now(UTC)
    async with database.sessions() as session:
        session.add(
            Workspace(
                id=workspace_id,
                owner_id=SYSTEM_USER_ID,
                name=name,
                lifecycle_state="active",
            )
        )
        await session.flush()
        session.add_all(
            (
                WorkspaceAuthorityVersion(
                    workspace_id=workspace_id,
                    authority_generation=1,
                    last_trace_id=trace_id,
                    updated_at=now,
                ),
                CollaborationAuditEvent(
                    audit_event_id=audit_id,
                    workspace_id=workspace_id,
                    actor_user_id=SYSTEM_USER_ID,
                    subject_kind="workspace_membership",
                    subject_id=membership_id,
                    action="membership.test_bootstrap",
                    outcome="succeeded",
                    reason_code="test_owner_bootstrap",
                    metadata_digest="0" * 64,
                    trace_id=trace_id,
                    recorded_at=now,
                ),
                WorkspaceMembership(
                    membership_id=membership_id,
                    user_id=SYSTEM_USER_ID,
                    workspace_id=workspace_id,
                    created_by_user_id=SYSTEM_USER_ID,
                    accepted_invitation_id=None,
                    collaboration_policy_version="collaboration-policy-v1",
                    creation_trace_id=trace_id,
                    creation_audit_event_id=audit_id,
                    created_at=now,
                ),
                Canvas(
                    id=canvas_id,
                    workspace_id=workspace_id,
                    name=f"{name} canvas",
                ),
            )
        )
        await session.flush()
        session.add(
            WorkspaceMembershipTransition(
                transition_id=uuid.uuid5(membership_id, "bootstrap-transition"),
                membership_id=membership_id,
                user_id=SYSTEM_USER_ID,
                workspace_id=workspace_id,
                sequence=0,
                previous_state=None,
                current_state="active",
                previous_role=None,
                current_role="owner",
                reason_code="test_owner_bootstrap",
                collaboration_policy_version="collaboration-policy-v1",
                authority_generation=1,
                actor_user_id=SYSTEM_USER_ID,
                trace_id=trace_id,
                audit_event_id=audit_id,
                recorded_at=now,
            )
        )
        await session.commit()
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    return workspace_id, canvas_id


async def _upload_ready_document(
    client: httpx.AsyncClient,
    api_prefix: str,
    canvas_id: str,
    *,
    content: bytes = b"SolarPlexus deterministic indexing evidence. Exact citation source.",
) -> JsonObject:
    response = await client.post(
        f"{api_prefix}/canvases/{canvas_id}/documents",
        files={
            "file": (
                "deterministic.txt",
                content,
                "text/plain",
            )
        },
        data={"x": "80", "y": "120"},
    )
    assert response.status_code == 201, response.text
    document = cast(JsonObject, response.json()["document"])
    status_response = await client.get(f"{api_prefix}/documents/{document['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "ready"
    return document


async def test_native_index_request_publishes_once_and_replay_is_read_only(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Indexer evidence")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    document = await _upload_ready_document(client, api_prefix, str(canvas_id))
    endpoint = (
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/documents/{document['id']}/versions/1/index-requests"
    )

    created = await client.post(endpoint, json={"idempotencyKey": "index-native-001"})
    assert created.status_code == 202, created.text
    request = cast(JsonObject, created.json())
    status_response = await client.get(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/index-requests/{request['requestId']}"
    )
    assert status_response.status_code == 200, status_response.text
    status_payload = cast(JsonObject, status_response.json())
    assert status_payload["state"] == "published"
    assert status_payload["revisionId"]
    assert status_payload["publicationId"]

    replay = await client.post(endpoint, json={"idempotencyKey": "index-native-001"})
    assert replay.status_code == 202, replay.text
    assert replay.json()["requestId"] == request["requestId"]
    assert replay.json()["duplicate"] is True
    assert replay.json()["state"] == "published"

    reindex = await client.post(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/documents/{document['id']}/reindex",
        json={"idempotencyKey": "index-reindex-001"},
    )
    assert reindex.status_code == 202, reindex.text
    reindex_status = await client.get(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/index-requests/{reindex.json()['requestId']}"
    )
    assert reindex_status.status_code == 200
    assert reindex_status.json()["state"] == "published"

    revisions = await client.get(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/documents/{document['id']}/index-revisions"
    )
    assert revisions.status_code == 200, revisions.text
    assert len(revisions.json()) == 2
    assert sum(item["active"] for item in revisions.json()) == 1

    async with database.sessions() as session:
        document_id = uuid.UUID(cast(str, document["id"]))
        assert await session.scalar(select(func.count()).select_from(IngestionRequest)) == 2
        assert await session.scalar(select(func.count()).select_from(IndexRevision)) == 2
        assert await session.scalar(select(func.count()).select_from(IndexPublication)) == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RetrievalHead)
                .where(RetrievalHead.document_id == document_id)
            )
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(IndexRevisionChunk))
        assert await session.scalar(select(func.count()).select_from(VectorMaterialization))
        deduplicated = await session.scalar(
            select(func.count())
            .select_from(IndexRevision)
            .where(IndexRevision.deduplication_kind == "exact_bytes")
        )
        reused_vectors = await session.scalar(
            select(func.count())
            .select_from(VectorMaterialization)
            .where(VectorMaterialization.reused_from_materialization_id.is_not(None))
        )
        assert deduplicated == 1
        assert reused_vectors
        with pytest.raises(DocumentProcessingError) as retained:
            await delete_document(session, document_id=document_id)
        assert retained.value.code == "document_index_history_retained"
        assert retained.value.status_code == 409
        await session.rollback()


async def test_cross_scope_access_and_deduplication_fail_closed(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
) -> None:
    first = await _create_canvas(client, api_prefix, "Indexer workspace one")
    first_workspace = uuid.UUID(cast(str, first["workspaceId"]))
    first_canvas = uuid.UUID(cast(str, first["id"]))
    second_workspace, second_canvas = await _create_isolated_workspace_canvas(
        database,
        name="Indexer workspace two",
    )
    await _register_canvas_resource(
        database,
        workspace_id=first_workspace,
        canvas_id=first_canvas,
    )
    first_document = await _upload_ready_document(client, api_prefix, str(first_canvas))
    second_document = await _upload_ready_document(client, api_prefix, str(second_canvas))

    first_response = await client.post(
        f"{api_prefix}/workspaces/{first_workspace}/canvases/{first_canvas}"
        f"/documents/{first_document['id']}/versions/1/index-requests",
        json={"idempotencyKey": "index-isolation-first"},
    )
    second_response = await client.post(
        f"{api_prefix}/workspaces/{second_workspace}/canvases/{second_canvas}"
        f"/documents/{second_document['id']}/versions/1/index-requests",
        json={"idempotencyKey": "index-isolation-second"},
    )
    assert first_response.status_code == 202, first_response.text
    assert second_response.status_code == 202, second_response.text

    hidden_status = await client.get(
        f"{api_prefix}/workspaces/{second_workspace}/canvases/{second_canvas}"
        f"/index-requests/{first_response.json()['requestId']}"
    )
    hidden_document = await client.post(
        f"{api_prefix}/workspaces/{second_workspace}/canvases/{second_canvas}"
        f"/documents/{first_document['id']}/versions/1/index-requests",
        json={"idempotencyKey": "index-isolation-hidden"},
    )
    assert hidden_status.status_code == 404
    assert hidden_status.json()["code"] == "index_not_found"
    assert hidden_document.status_code == 404
    assert hidden_document.json()["code"] == "index_not_found"

    async with database.sessions() as session:
        revisions = list(
            (
                await session.scalars(
                    select(IndexRevision).where(
                        IndexRevision.document_id.in_(
                            (
                                uuid.UUID(cast(str, first_document["id"])),
                                uuid.UUID(cast(str, second_document["id"])),
                            )
                        )
                    )
                )
            ).all()
        )
        assert len(revisions) == 2
        assert {revision.workspace_id for revision in revisions} == {
            first_workspace,
            second_workspace,
        }
        assert {revision.deduplication_kind for revision in revisions} == {"none"}


async def test_concurrent_duplicate_publication_advances_one_head_once(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Indexer concurrent publication")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    document = await _upload_ready_document(client, api_prefix, str(canvas_id))
    document_id = uuid.UUID(cast(str, document["id"]))
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
        document_storage_root=tmp_path / "documents",
    )
    principal = Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        view = await service.request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=1,
            idempotency_key="index-concurrent-publication",
        )
        await session.commit()
    async with database.sessions() as session:
        revision = await IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        ).build(view.request.request_id)
        assert revision is not None
        revision_id = revision.revision_id
        await session.commit()

    async def publish_once() -> uuid.UUID:
        async with database.sessions() as session:
            publication = await IngestionService(
                session,
                settings=settings,
                storage=build_document_storage(settings),
                provider=build_embedding_provider(settings),
            ).publish(view.request.request_id, revision_id)
            assert publication is not None
            publication_id = publication.publication_id
            await session.commit()
            return publication_id

    publication_ids = await asyncio.gather(publish_once(), publish_once())
    assert publication_ids[0] == publication_ids[1]
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(IndexPublication)) == 1
        head = await session.get(RetrievalHead, document_id)
        assert head is not None
        assert head.generation == 1
        transitions = list(
            (
                await session.scalars(
                    select(IngestionRequestTransition.current_state)
                    .where(IngestionRequestTransition.request_id == view.request.request_id)
                    .order_by(IngestionRequestTransition.sequence)
                )
            ).all()
        )
        assert transitions.count("published") == 1


async def test_normalized_content_dedup_reuses_vectors_only_within_workspace(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Indexer normalized dedup")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    first = await _upload_ready_document(
        client,
        api_prefix,
        str(canvas_id),
        content=b"Normalized   source\r\nwith stable evidence.",
    )
    second = await _upload_ready_document(
        client,
        api_prefix,
        str(canvas_id),
        content=b"Normalized source\nwith stable evidence.",
    )
    for ordinal, document in enumerate((first, second), start=1):
        response = await client.post(
            f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
            f"/documents/{document['id']}/versions/1/index-requests",
            json={"idempotencyKey": f"index-normalized-{ordinal}"},
        )
        assert response.status_code == 202, response.text

    async with database.sessions() as session:
        second_revision = await session.scalar(
            select(IndexRevision).where(
                IndexRevision.document_id == uuid.UUID(cast(str, second["id"]))
            )
        )
        assert second_revision is not None
        assert second_revision.deduplication_kind == "normalized_content"
        assert second_revision.deduplicated_from_revision_id is not None
        reused = await session.scalar(
            select(func.count())
            .select_from(VectorMaterialization)
            .where(
                VectorMaterialization.revision_id == second_revision.revision_id,
                VectorMaterialization.reused_from_materialization_id.is_not(None),
            )
        )
        assert reused and reused > 0


async def test_component_drift_and_source_change_block_publication(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Indexer deterministic drift")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    document = await _upload_ready_document(client, api_prefix, str(canvas_id))
    document_id = uuid.UUID(cast(str, document["id"]))
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
        document_storage_root=tmp_path / "documents",
    )
    principal = Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )

    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        first = await service.request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=1,
            idempotency_key="index-drift-first",
        )
        await session.commit()
    async with database.sessions() as session:
        first_revision = await IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        ).build(first.request.request_id)
        assert first_revision is not None
        await session.commit()

    async with database.sessions() as session:
        second = await IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        ).request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=1,
            idempotency_key="index-drift-second",
            operation="reindex",
        )
        await session.commit()

    stable_chunker = indexer_module.chunk_document

    def drifted_chunker(*args: object, **kwargs: object) -> list[object]:
        chunks = list(stable_chunker(*args, **kwargs))
        assert chunks
        chunks[0] = replace(chunks[0], content=f"{chunks[0].content} drift")
        return chunks

    monkeypatch.setattr(indexer_module, "chunk_document", drifted_chunker)
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        with pytest.raises(IndexerError) as drifted:
            await service.build(second.request.request_id)
        assert drifted.value.code == "nondeterministic_dependency_output"
        await session.rollback()
    monkeypatch.setattr(indexer_module, "chunk_document", stable_chunker)

    async with database.sessions() as session:
        await session.execute(
            update(Document).where(Document.id == document_id).values(current_version=2)
        )
        await session.commit()
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        with pytest.raises(IndexerError) as changed:
            await service.publish(
                first.request.request_id,
                first_revision.revision_id,
            )
        assert changed.value.code == "source_changed"
        await session.rollback()
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(IndexPublication)) == 0
        assert await session.get(RetrievalHead, document_id) is None


async def test_cancel_and_conflicting_idempotency_fail_closed(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Indexer cancellation")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    document = await _upload_ready_document(client, api_prefix, str(canvas_id))

    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
    )
    principal = Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        view = await service.request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=uuid.UUID(cast(str, document["id"])),
            document_version=1,
            idempotency_key="index-cancel-001",
        )
        canceled = await service.cancel(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            request_id=view.request.request_id,
        )
        replay = await service.cancel(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            request_id=view.request.request_id,
        )
        assert canceled.transition.current_state == "canceled"
        assert replay.transition.transition_id == canceled.transition.transition_id
        await session.commit()

    conflict = await client.post(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/documents/{document['id']}/reindex",
        json={"idempotencyKey": "index-cancel-001"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "index_conflict"

    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(IngestionRequest)) == 1
        states = list(
            (
                await session.scalars(
                    select(IngestionRequestTransition.current_state).order_by(
                        IngestionRequestTransition.sequence
                    )
                )
            ).all()
        )
        assert states == ["requested", "queued", "canceled"]
        assert await session.scalar(select(func.count()).select_from(IndexRevision)) == 0
        assert await session.scalar(select(func.count()).select_from(IndexPublication)) == 0
        assert await session.scalar(select(func.count()).select_from(IndexerAuditEvent)) == 2


async def test_unpublished_revision_is_not_retrievable(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Unpublished index")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    document = await _upload_ready_document(client, api_prefix, str(canvas_id))
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
        document_storage_root=tmp_path / "documents",
        indexer_publication_mode="disabled",
    )
    principal = Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )
    async with database.sessions() as session:
        view = await IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        ).request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=uuid.UUID(cast(str, document["id"])),
            document_version=1,
            idempotency_key="index-unpublished-001",
        )
        await session.commit()
    await process_ingestion_request(
        database.sessions,
        request_id=view.request.request_id,
        settings=settings,
        storage=build_document_storage(settings),
        provider=build_embedding_provider(settings),
    )
    status_response = await client.get(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/index-requests/{view.request.request_id}"
    )
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "completed"
    search = await client.post(
        f"{api_prefix}/canvases/{canvas_id}/documents/search",
        json={
            "query": "SolarPlexus indexing evidence",
            "documentIds": [document["id"]],
        },
    )
    assert search.status_code == 200, search.text
    assert search.json()["matches"] == []
    assert search.json()["insufficientContext"] is True
    async with database.sessions() as session:
        assert (
            await session.get(
                RetrievalHead,
                uuid.UUID(cast(str, document["id"])),
            )
            is None
        )


async def test_revision_transaction_failure_leaves_only_safe_terminal_evidence(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Indexer atomic failure")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    document = await _upload_ready_document(client, api_prefix, str(canvas_id))
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
        document_storage_root=tmp_path / "documents",
    )
    principal = Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )
    async with database.sessions() as session:
        view = await IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        ).request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=uuid.UUID(cast(str, document["id"])),
            document_version=1,
            idempotency_key="index-failure-001",
        )
        await session.commit()

    async def fail_after_revision() -> None:
        raise RuntimeError("injected revision transaction failure")

    await process_ingestion_request(
        database.sessions,
        request_id=view.request.request_id,
        settings=settings,
        storage=build_document_storage(settings),
        provider=build_embedding_provider(settings),
        hooks=IndexerHooks(after_revision=fail_after_revision),
    )
    async with database.sessions() as session:
        latest = await session.scalar(
            select(IngestionRequestTransition)
            .where(IngestionRequestTransition.request_id == view.request.request_id)
            .order_by(IngestionRequestTransition.sequence.desc())
            .limit(1)
        )
        assert latest is not None and latest.current_state == "failed"
        for model in (
            NormalizedArtifact,
            IndexRevision,
            IndexRevisionChunk,
            VectorMaterialization,
            IndexPublication,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert await session.scalar(select(func.count()).select_from(IndexerFailure)) == 1
        event_types = list(
            (
                await session.scalars(
                    select(DomainEventRecord.event_type).order_by(DomainEventRecord.sequence)
                )
            ).all()
        )
        assert event_types == [
            "ingestion.requested",
            "ingestion.queued",
            "ingestion.failed",
        ]
        trace_states = list(
            (
                await session.scalars(
                    select(TraceEvent.status)
                    .where(TraceEvent.trace_id == view.request.trace_id)
                    .order_by(TraceEvent.occurred_at, TraceEvent.event_id)
                )
            ).all()
        )
        assert trace_states == ["started", "failed"]


async def test_canceled_and_revoked_workers_cannot_publish(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Indexer stale workers")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    document = await _upload_ready_document(client, api_prefix, str(canvas_id))
    document_id = uuid.UUID(cast(str, document["id"]))
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
        document_storage_root=tmp_path / "documents",
    )
    principal = Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )

    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        canceled_request = await service.request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=1,
            idempotency_key="index-stale-cancel-001",
        )
        await session.commit()
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        revision = await service.build(canceled_request.request.request_id)
        assert revision is not None
        await session.commit()
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        await service.cancel(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            request_id=canceled_request.request.request_id,
        )
        await session.commit()
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        with pytest.raises(IndexerError, match="completed revision"):
            await service.publish(
                canceled_request.request.request_id,
                revision.revision_id,
            )
        await session.rollback()

    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        revoked_request = await service.request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=1,
            idempotency_key="index-stale-revoked-001",
            operation="reindex",
        )
        await session.commit()
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        revoked_revision = await service.build(revoked_request.request.request_id)
        assert revoked_revision is not None
        await session.commit()
    async with database.sessions() as session:
        await session.execute(
            update(WorkspaceAuthorityVersion)
            .where(WorkspaceAuthorityVersion.workspace_id == workspace_id)
            .values(authority_generation=WorkspaceAuthorityVersion.authority_generation + 1)
        )
        await session.commit()
    async with database.sessions() as session:
        service = IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        with pytest.raises(IndexerError) as raised:
            await service.publish(
                revoked_request.request.request_id,
                revoked_revision.revision_id,
            )
        assert raised.value.code == "authority_revoked"
        await session.rollback()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(IndexPublication)) == 0
        assert await session.get(RetrievalHead, document_id) is None
