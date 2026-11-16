from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from opencanvas_api.api.routes import documents as document_routes
from opencanvas_api.core.config import get_settings
from opencanvas_api.db.models import (
    SYSTEM_WORKSPACE_ID,
    AIResponseSource,
    CanvasDocumentNode,
    Citation,
    Document,
    DocumentChunk,
    DocumentFile,
    DocumentProcessingJob,
    DocumentVersion,
    DurableJobRequest,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.documents import DocumentStorageError
from opencanvas_api.services.documents.embeddings import build_embedding_provider
from opencanvas_api.services.documents.errors import DocumentProcessingError
from opencanvas_api.services.documents.processing import DocumentProcessor
from opencanvas_api.services.documents.storage import build_document_storage
from opencanvas_api.services.durable_jobs import DurableJobService
from tests.test_canvas_api import _create_canvas
from tests.test_document_api import _upload
from tests.test_durable_jobs import _principal


@pytest.mark.parametrize("fail_unlink", [False, True])
async def test_legacy_delete_preserves_durable_history_and_fences_source(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    app: FastAPI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_unlink: bool,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Retained local document history")
    uploaded = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="durable-facts.txt",
        content=b"The observatory calibration code is NOVA-731 and it is verified.",
        media_type="text/plain",
    )
    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    document_id = uuid.UUID(payload["document"]["id"])
    ready = await client.get(f"{api_prefix}/documents/{document_id}")
    assert ready.json()["status"] == "ready"
    answer = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": "What is the observatory calibration code NOVA-731?",
            "selectedNodeIds": [payload["node"]["id"]],
        },
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["citations"]

    async with database.sessions() as session:
        version = await session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        )
        stored = await session.scalar(
            select(DocumentFile).where(DocumentFile.document_id == document_id)
        )
        chunk_id = await session.scalar(
            select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
        )
        assert version is not None and stored is not None and chunk_id is not None
        stored_path = tmp_path / "documents" / stored.storage_key
        assert stored_path.is_file()
        job = await DurableJobService(session).create_document_job(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=uuid.UUID(canvas["id"]),
            document_id=document_id,
            document_version_id=version.id,
            idempotency_key="retained-local-delete-history",
            deadline_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        await session.commit()
        job_id, request_id, version_id = job.id, job.request_id, version.id
        request = await session.get(DurableJobRequest, request_id)
        assert request is not None
        source = await session.get(Document, document_id)
        assert source is not None
        status_before = source.status
        intent_before = {
            column.name: getattr(request, column.name)
            for column in DurableJobRequest.__table__.columns
        }

    if fail_unlink:

        class FailingDeleteStorage:
            async def delete(self, storage_key: str) -> None:
                del storage_key
                raise DocumentStorageError("The stored document could not be removed.")

        monkeypatch.setattr(
            document_routes, "build_document_storage", lambda settings: FailingDeleteStorage()
        )

    async with database.sessions() as stale_session:
        cached_source = await stale_session.get(Document, document_id)
        assert cached_source is not None and cached_source.deleted_at is None
        deleted = await client.delete(f"{api_prefix}/documents/{document_id}")
        assert deleted.status_code == (500 if fail_unlink else 204), deleted.text
        async with database.sessions() as session:
            document = await session.get(Document, document_id)
            version = await session.get(DocumentVersion, version_id)
            request = await session.get(DurableJobRequest, request_id)
            assert document is not None and version is not None and request is not None
            assert await session.get(DocumentProcessingJob, job_id) is not None
            assert {
                column.name: getattr(request, column.name)
                for column in DurableJobRequest.__table__.columns
            } == intent_before
            assert (document.deleted_at is None) is fail_unlink
            assert (version.deleted_at is None) is fail_unlink
            assert document.status == (status_before if fail_unlink else "deleted")
            for model, predicate in (
                (CanvasDocumentNode, CanvasDocumentNode.document_id == document_id),
                (Citation, Citation.document_id == document_id),
                (AIResponseSource, AIResponseSource.document_id == document_id),
            ):
                remaining = (await session.scalars(select(model).where(predicate))).all()
                assert bool(remaining) is fail_unlink
        assert stored_path.exists() is fail_unlink

        if fail_unlink:
            assert deleted.json()["code"] == "storage_failed"
            assert (await client.get(f"{api_prefix}/documents/{document_id}")).status_code == 200
            return

        for suffix in ("", "/text", f"/chunks/{chunk_id}", "/file"):
            response = await client.get(f"{api_prefix}/documents/{document_id}{suffix}")
            assert response.status_code == 404, response.text
        retry = await client.post(f"{api_prefix}/documents/{document_id}/retry")
        assert retry.status_code == 404, retry.text
        search = await client.post(
            f"{api_prefix}/canvases/{canvas['id']}/documents/search",
            json={"query": "NOVA-731", "documentIds": [str(document_id)]},
        )
        assert search.status_code == 400 and search.json()["code"] == "invalid_selected_documents"

        # The processor must reject the tombstone before touching providers/storage,
        # including a stale queued force/retry invocation.
        settings = app.dependency_overrides[get_settings]()
        processor = DocumentProcessor(
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        with pytest.raises(DocumentProcessingError) as caught:
            await processor.process_with_session(
                stale_session,
                document_id,
                force=True,
                manage_job=False,
            )
        assert caught.value.code == "document_not_found"
        assert cached_source.status == "deleted"
