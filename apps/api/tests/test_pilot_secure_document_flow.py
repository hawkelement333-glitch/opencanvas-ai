from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.core.config import get_settings
from opencanvas_api.db.models import (
    CanvasDocumentNode,
    CanvasNode,
    Document,
    DocumentProcessingJob,
    DurableJobOutcome,
    IndexPublication,
    MalwareScanRequest,
    RetrievalHead,
    StorageObjectVersion,
    WorkspaceAuthorityVersion,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.durable_jobs import DurableJobConflictError, DurableJobService
from opencanvas_api.services.jobs import DocumentWorker
from opencanvas_api.services.object_ingestion import (
    ObjectReconciler,
    TrustedScanResult,
    scanner_result_signature,
)
from tests.test_canvas_api import _create_canvas
from tests.test_indexer import _register_canvas_resource
from tests.test_object_ingestion import _settings


@pytest.mark.parametrize(
    "outcome", ["clean", "timeout", "lease_conflict", "revoked", "observational_read_failure"]
)
async def test_pilot_secure_document_card_deadline_worker_and_retrieval(
    app: FastAPI,
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
    outcome: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        tmp_path,
        storage_provider="local",
        job_provider="database",
        malware_scan_timeout_seconds=900,
        scanner_result_bridge_retry_max_seconds=20,
    )
    if outcome == "observational_read_failure":
        from opencanvas_api.services import operational_observations

        async def unavailable_observer(*args, **kwargs):
            raise RuntimeError("local observational read failure")

        monkeypatch.setattr(
            operational_observations, "observe_workspace_state", unavailable_observer
        )
    app.dependency_overrides[get_settings] = lambda: settings
    if hasattr(app.state, "versioned_object_storage"):
        del app.state.versioned_object_storage
    canvas = await _create_canvas(client, api_prefix, "Pilot secure document")
    workspace_id, canvas_id = uuid.UUID(canvas["workspaceId"]), uuid.UUID(canvas["id"])
    await _register_canvas_resource(database, workspace_id=workspace_id, canvas_id=canvas_id)
    content = b"The observatory calibration code is NOVA-731. Its aperture is 6.5 meters."
    scope = f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions"
    payload = {
        "fileName": "pilot.txt",
        "mediaType": "text/plain",
        "sizeBytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "idempotencyKey": "pilot-card",
        "x": 123,
        "y": 234,
    }
    initiated = await client.post(scope, json=payload)
    assert initiated.status_code == 201, initiated.text
    upload = initiated.json()
    replay = await client.post(scope, json=payload)
    assert replay.status_code == 201 and replay.json()["sessionId"] == upload["sessionId"]
    async with database.sessions() as session:
        cards = (
            await session.scalars(
                select(CanvasDocumentNode).where(
                    CanvasDocumentNode.document_id == uuid.UUID(upload["documentId"])
                )
            )
        ).all()
        assert len(cards) == 1, "Secure upload must create exactly one persistent canvas card"
        node = await session.get(CanvasNode, cards[0].node_id)
        assert node is not None and (node.position_x, node.position_y) == (123, 234)
        assert await session.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 0
    stored = await client.put(
        upload["uploadPath"], content=content, headers={"X-Upload-Capability": upload["capability"]}
    )
    assert stored.status_code == 200, stored.text
    completed = await client.post(f"{scope}/{upload['sessionId']}/complete")
    assert completed.status_code == 200, completed.text
    pending = completed.json()
    deadline = datetime.fromisoformat(pending["scanDeadlineAt"].replace("Z", "+00:00"))
    assert deadline > datetime.fromisoformat(
        pending["expiresAt"].replace("Z", "+00:00")
    ) + timedelta(seconds=590)
    reloaded = await client.get(f"{api_prefix}/documents/{upload['documentId']}/upload-session")
    assert reloaded.status_code == 200 and reloaded.json()["sessionId"] == upload["sessionId"]
    assert reloaded.json()["capability"] is None
    assert reloaded.json()["objectState"] == "scan_pending"
    denied = await client.get(f"{scope}/{upload['sessionId']}/file")
    assert denied.status_code == 404
    worker = DocumentWorker(
        settings=settings, sessions=database.sessions, worker_id="pilot-local-worker"
    )
    assert await worker.run_once() is False
    async with database.sessions() as session:
        request = await session.scalar(
            select(MalwareScanRequest).where(
                MalwareScanRequest.object_version_id == uuid.UUID(upload["objectVersionId"])
            )
        )
        version = await session.get(StorageObjectVersion, uuid.UUID(upload["objectVersionId"]))
        assert request is not None and version is not None
        if outcome == "timeout":
            assert (
                await ObjectReconciler(session, settings=settings).expire_scan_requests(
                    now=deadline + timedelta(seconds=1)
                )
                == 1
            )
            await session.commit()
    if outcome == "timeout":
        timed = await client.get(f"{scope}/{upload['sessionId']}")
        assert timed.json()["safeReasonCode"] == "scan_timeout"
        assert timed.json()["objectState"] == "error"
        assert await worker.run_once() is False
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 0
            )
        return
    result = TrustedScanResult(
        scan_request_id=request.scan_request_id,
        object_version_id=version.object_version_id,
        workspace_id=workspace_id,
        outcome="clean",
        scanner_identity=request.scanner_identity,
        scanner_version=request.scanner_version,
        engine_version="local-test",
        signature_version="local-test",
        policy_version=request.policy_version,
        provider_result_id="pilot-local-clean",
        provider_record_digest=hashlib.sha256(b"local-test").hexdigest(),
        provider_version_id=version.provider_version_id,
        etag=version.etag,
        content_sha256=version.content_sha256,
        scanned_at=datetime.now(UTC),
        safe_reason_code="no_threats_found",
    )
    scanned = await client.post(
        f"{api_prefix}/internal/object-ingestion/scan-results",
        json=result.canonical_payload(),
        headers={
            "X-Scanner-Result-Signature": scanner_result_signature(
                result, settings.scanner_result_secret
            )
        },
    )
    assert scanned.status_code == 200, scanned.text
    if outcome == "lease_conflict":

        async def reject_completion(service, lease, **effects):
            assert effects["result_id"] is not None and effects["publication_id"] is not None
            assert (
                await service.session.get(IndexPublication, effects["publication_id"]) is not None
            )
            raise DurableJobConflictError("Synthetic lease loss after publication")

        monkeypatch.setattr(DurableJobService, "complete", reject_completion)
    if outcome == "revoked":
        async with database.sessions() as session:
            authority = await session.get(WorkspaceAuthorityVersion, workspace_id)
            assert authority is not None
            authority.authority_generation += 1
            await session.commit()
        assert await worker.run_once() is False
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 0
            )
            assert await session.get(RetrievalHead, uuid.UUID(upload["documentId"])) is None
            doc = await session.get(Document, uuid.UUID(upload["documentId"]))
            assert doc is not None and doc.safe_error_category == "authority_revoked"
        return
    assert await worker.run_once() is True
    if outcome == "lease_conflict":
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(IndexPublication)) == 0
            assert await session.scalar(select(func.count()).select_from(RetrievalHead)) == 0
            assert await session.scalar(select(func.count()).select_from(DurableJobOutcome)) == 0
            doc = await session.get(Document, uuid.UUID(upload["documentId"]))
            assert doc is not None and doc.status == "queued"
        return
    assert await worker.run_once() is False
    async with database.sessions() as session:
        doc = await session.get(Document, uuid.UUID(upload["documentId"]))
        assert doc is not None and doc.status == "ready"
        head = await session.get(RetrievalHead, doc.id)
        assert head is not None
        result = await session.scalar(select(DurableJobOutcome))
        assert result is not None
        assert result.result_id == head.revision_id and result.publication_id == head.publication_id
        assert await session.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 1
    search = await client.post(
        f"{api_prefix}/canvases/{canvas_id}/documents/search",
        json={"query": "NOVA-731", "documentIds": [upload["documentId"]]},
    )
    assert search.status_code == 200, search.text
    assert search.json()["matches"] and not search.json()["insufficientContext"]
