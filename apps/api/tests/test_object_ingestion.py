from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    DocumentChunk,
    DomainEventRecord,
    MalwareScanRequest,
    MalwareScanResult,
    ObjectDeletionRequest,
    ObjectPromotion,
    StorageObjectLifecycleTransition,
    StorageObjectVersion,
    WorkspaceAuthorityVersion,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.documents import (
    MemoryDocumentStorage,
    MemoryVersionedObjectStorage,
    MockEmbeddingProvider,
    validate_document_bytes,
)
from opencanvas_api.services.documents.errors import (
    DocumentStorageError,
    DocumentValidationError,
)
from opencanvas_api.services.indexer import IndexerError, IngestionService
from opencanvas_api.services.object_ingestion import (
    MalwareScanService,
    ObjectIngestionError,
    ObjectIngestionNotFoundError,
    ObjectReconciler,
    TrustedScanResult,
    UploadLifecycleService,
    UploadSessionView,
    scanner_result_signature,
)
from tests.test_canvas_api import _create_canvas
from tests.test_indexer import (
    _create_isolated_workspace_canvas,
    _register_canvas_resource,
)


def _settings(tmp_path: Path, **changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "auth_test_bypass": True,
        "storage_provider": "memory",
        "document_storage_root": tmp_path / "documents",
        "object_ingestion_mode": "deterministic",
        "upload_capability_secret": "upload-capability-test-secret-000000000000",
        "scanner_result_secret": "scanner-result-test-secret-00000000000000",
        "malware_scanner_identity": "deterministic-test-scanner",
        "malware_scanner_version": "test-v1",
        "malware_policy_version": "test-policy-v1",
        "indexer_publication_mode": "private_clean",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def _principal() -> Principal:
    return Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )


async def _completed_upload(
    database: Database,
    tmp_path: Path,
    *,
    content: bytes = b"bounded secure upload evidence",
    settings_changes: dict[str, object] | None = None,
) -> tuple[
    Settings,
    MemoryVersionedObjectStorage,
    uuid.UUID,
    uuid.UUID,
    UploadSessionView,
]:
    settings = _settings(tmp_path, **(settings_changes or {}))
    storage = MemoryVersionedObjectStorage()
    workspace_id, canvas_id = await _create_isolated_workspace_canvas(
        database,
        name=f"secure-{uuid.uuid4().hex[:8]}",
    )
    digest = hashlib.sha256(content).hexdigest()
    async with database.sessions() as session:
        service = UploadLifecycleService(session, settings=settings, storage=storage)
        initiated = await service.initiate(
            principal=_principal(),
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            file_name="evidence.txt",
            media_type="text/plain",
            size_bytes=len(content),
            sha256=digest,
            idempotency_key=f"upload-{uuid.uuid4().hex}",
        )
        assert initiated.capability is not None
        await service.upload_bytes(
            session_id=initiated.session.session_id,
            capability=initiated.capability,
            content=content,
        )
        completed = await service.complete(
            principal=_principal(),
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=initiated.session.session_id,
        )
        await session.commit()
    return settings, storage, workspace_id, canvas_id, completed


def _scan_result(
    view: UploadSessionView,
    *,
    outcome: str = "clean",
    scanned_at: datetime | None = None,
    policy_version: str | None = None,
) -> TrustedScanResult:
    request = view.scan_request
    assert request is not None
    version = view.object_transition
    assert version is not None
    return TrustedScanResult(
        scan_request_id=request.scan_request_id,
        object_version_id=request.object_version_id,
        workspace_id=request.workspace_id,
        outcome=outcome,  # type: ignore[arg-type]
        scanner_identity=request.scanner_identity,
        scanner_version=request.scanner_version,
        engine_version="engine-test-v1",
        signature_version="signatures-test-v1",
        policy_version=policy_version or request.policy_version,
        provider_result_id=f"provider-{uuid.uuid4().hex}",
        provider_record_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        provider_version_id="",
        etag="",
        content_sha256="",
        scanned_at=scanned_at or datetime.now(UTC),
        safe_reason_code="no_threats_found" if outcome == "clean" else f"scan_{outcome}",
    )


async def _bind_result(
    database: Database,
    view: UploadSessionView,
    result: TrustedScanResult,
) -> TrustedScanResult:
    async with database.sessions() as session:
        version = await session.get(StorageObjectVersion, view.session.object_version_id)
        assert version is not None
        return replace(
            result,
            provider_version_id=version.provider_version_id,
            etag=version.etag,
            content_sha256=version.content_sha256,
        )


@pytest.mark.asyncio
async def test_clean_verdict_promotes_exact_bytes_once(database: Database, tmp_path: Path) -> None:
    settings, storage, workspace_id, canvas_id, completed = await _completed_upload(
        database, tmp_path
    )
    result = await _bind_result(database, completed, _scan_result(completed))
    signature = scanner_result_signature(result, settings.scanner_result_secret)

    async with database.sessions() as session:
        scan = MalwareScanService(session, settings=settings, storage=storage)
        first = await scan.record_result(result=result, signature=signature)
        duplicate = await scan.record_result(result=result, signature=signature)
        clean = await UploadLifecycleService(
            session, settings=settings, storage=storage
        ).clean_bytes(
            principal=_principal(),
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=completed.session.session_id,
        )
        await session.commit()
        assert first.object_transition is not None
        assert first.object_transition.current_state == "clean"
        assert duplicate.promotion is not None
        assert clean[2] == b"bounded secure upload evidence"
        assert await session.scalar(select(func.count()).select_from(MalwareScanResult)) == 1
        assert await session.scalar(select(func.count()).select_from(ObjectPromotion)) == 1
        assert await session.scalar(select(func.count()).select_from(StorageObjectVersion)) == 2


@pytest.mark.asyncio
async def test_private_bridge_records_sanitized_dual_source_evidence(
    database: Database,
    tmp_path: Path,
) -> None:
    settings, storage, _workspace_id, _canvas_id, completed = await _completed_upload(
        database,
        tmp_path,
        settings_changes={
            "scanner_result_bridge_mode": "private_pull",
            "malware_scanner_identity": "azure-defender-for-storage",
            "malware_scanner_version": "defender-storage-dual-source-v1",
        },
    )
    result = await _bind_result(database, completed, _scan_result(completed))
    result = replace(
        result,
        scanner_identity="azure-defender-for-storage",
        scanner_version="defender-storage-dual-source-v1",
        provider_result_id="00000000-0000-4000-8000-000000000077",
    )
    integrity = "a" * 64
    evidence = {
        "scannerEvidenceIntegrity": integrity,
        "scannerCorrelationSha256": "b" * 64,
        "scannerBlobTagEvidenceSha256": "c" * 64,
        "scannerLogAnalyticsEvidenceSha256": "d" * 64,
        "scannerBlobUriSha256": "e" * 64,
        "scannerEtagSha256": "f" * 64,
        "scannerCompletionAtUtc": result.scanned_at.isoformat().replace("+00:00", "Z"),
        "scannerProvenance": ("defender-blob-tags-plus-storage-malware-scanning-results"),
    }

    async with database.sessions() as session:
        view = await MalwareScanService(
            session,
            settings=settings,
            storage=storage,
        ).record_bridge_result(
            result=result,
            evidence_integrity_sha256=integrity,
            event_evidence=evidence,
        )
        event = await session.scalar(
            select(DomainEventRecord)
            .where(DomainEventRecord.event_type == "scan.passed")
            .order_by(DomainEventRecord.created_at.desc())
            .limit(1)
        )
        assert view.promotion is not None
        assert event is not None
        assert event.payload["scannerEvidenceIntegrity"] == integrity
        assert event.payload["scannerCorrelationSha256"] == "b" * 64
        assert "blob.core.windows.net" not in json.dumps(event.payload)


@pytest.mark.asyncio
async def test_private_bridge_makes_legacy_push_callback_unreachable(
    database: Database,
    tmp_path: Path,
) -> None:
    settings, storage, _workspace_id, _canvas_id, completed = await _completed_upload(
        database,
        tmp_path,
        settings_changes={
            "scanner_result_bridge_mode": "private_pull",
            "malware_scanner_identity": "azure-defender-for-storage",
            "malware_scanner_version": "defender-storage-dual-source-v1",
        },
    )
    result = await _bind_result(database, completed, _scan_result(completed))
    async with database.sessions() as session:
        with pytest.raises(ObjectIngestionNotFoundError):
            await MalwareScanService(
                session,
                settings=settings,
                storage=storage,
            ).record_result(
                result=result,
                signature=scanner_result_signature(result, settings.scanner_result_secret),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    ["infected", "suspicious", "unsupported", "error", "timeout"],
)
async def test_non_clean_outcomes_never_promote(
    database: Database,
    tmp_path: Path,
    outcome: str,
) -> None:
    settings, storage, workspace_id, canvas_id, completed = await _completed_upload(
        database, tmp_path, content=f"outcome:{outcome}".encode()
    )
    result = await _bind_result(
        database,
        completed,
        _scan_result(completed, outcome=outcome),
    )
    async with database.sessions() as session:
        view = await MalwareScanService(session, settings=settings, storage=storage).record_result(
            result=result,
            signature=scanner_result_signature(result, settings.scanner_result_secret),
        )
        assert view.object_transition is not None
        assert view.object_transition.current_state == "rejected"
        assert await session.scalar(select(func.count()).select_from(ObjectPromotion)) == 0
        with pytest.raises(ObjectIngestionNotFoundError):
            await UploadLifecycleService(session, settings=settings, storage=storage).clean_bytes(
                principal=_principal(),
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                session_id=completed.session.session_id,
            )


@pytest.mark.asyncio
async def test_forged_mismatched_stale_and_late_results_fail_closed(
    database: Database,
    tmp_path: Path,
) -> None:
    settings, storage, _, _, completed = await _completed_upload(database, tmp_path)
    valid = await _bind_result(database, completed, _scan_result(completed))
    async with database.sessions() as session:
        scanner = MalwareScanService(session, settings=settings, storage=storage)
        with pytest.raises(ObjectIngestionNotFoundError):
            await scanner.record_result(result=valid, signature="0" * 64)
        mismatched = replace(valid, content_sha256="f" * 64)
        with pytest.raises(ObjectIngestionError, match="does not match"):
            await scanner.record_result(
                result=mismatched,
                signature=scanner_result_signature(
                    mismatched,
                    settings.scanner_result_secret,
                ),
            )
        late = replace(
            valid,
            scanned_at=datetime.now(UTC)
            + timedelta(seconds=settings.malware_scan_timeout_seconds + 1),
        )
        with pytest.raises(ObjectIngestionError, match="does not match"):
            await scanner.record_result(
                result=late,
                signature=scanner_result_signature(late, settings.scanner_result_secret),
            )
        changed_policy = settings.model_copy(update={"malware_policy_version": "test-policy-v2"})
        with pytest.raises(ObjectIngestionError, match="does not match"):
            await MalwareScanService(
                session,
                settings=changed_policy,
                storage=storage,
            ).record_result(
                result=valid,
                signature=scanner_result_signature(
                    valid,
                    changed_policy.scanner_result_secret,
                ),
            )
        assert await session.scalar(select(func.count()).select_from(MalwareScanResult)) == 0
        assert await session.scalar(select(func.count()).select_from(ObjectPromotion)) == 0


@pytest.mark.asyncio
async def test_cancellation_and_authority_change_fence_scanner_commit(
    database: Database,
    tmp_path: Path,
) -> None:
    settings, storage, workspace_id, canvas_id, completed = await _completed_upload(
        database, tmp_path
    )
    result = await _bind_result(database, completed, _scan_result(completed))
    async with database.sessions() as session:
        service = UploadLifecycleService(session, settings=settings, storage=storage)
        canceled = await service.cancel(
            principal=_principal(),
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=completed.session.session_id,
        )
        assert canceled.transition.current_state == "canceled"
        with pytest.raises(ObjectIngestionError, match="does not match"):
            await MalwareScanService(session, settings=settings, storage=storage).record_result(
                result=result,
                signature=scanner_result_signature(result, settings.scanner_result_secret),
            )
        assert await session.scalar(select(func.count()).select_from(MalwareScanResult)) == 0

    _, _, workspace_id_2, _, completed_2 = await _completed_upload(
        database,
        tmp_path,
        content=b"authority fenced upload",
    )
    result_2 = await _bind_result(database, completed_2, _scan_result(completed_2))
    async with database.sessions() as session:
        authority = await session.get(WorkspaceAuthorityVersion, workspace_id_2)
        assert authority is not None
        authority.authority_generation += 1
        await session.commit()
    async with database.sessions() as session:
        with pytest.raises(ObjectIngestionError, match="does not match"):
            await MalwareScanService(session, settings=settings, storage=storage).record_result(
                result=result_2,
                signature=scanner_result_signature(result_2, settings.scanner_result_secret),
            )


@pytest.mark.asyncio
async def test_cross_scope_capability_and_contract_substitution_fail(
    database: Database,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    storage = MemoryVersionedObjectStorage()
    workspace_a, canvas_a = await _create_isolated_workspace_canvas(database, name="scope-a")
    workspace_b, canvas_b = await _create_isolated_workspace_canvas(database, name="scope-b")
    content = b"scope-bound bytes"
    async with database.sessions() as session:
        service = UploadLifecycleService(session, settings=settings, storage=storage)
        view = await service.initiate(
            principal=_principal(),
            workspace_id=workspace_a,
            canvas_id=canvas_a,
            file_name="scope.txt",
            media_type="text/plain",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            idempotency_key="scope-upload",
        )
        assert view.capability is not None
        with pytest.raises(ObjectIngestionNotFoundError):
            await service.get(
                principal=_principal(),
                workspace_id=workspace_b,
                canvas_id=canvas_b,
                session_id=view.session.session_id,
            )
        with pytest.raises(ObjectIngestionNotFoundError):
            await service.get(
                principal=Principal(
                    user_id=uuid.uuid4(),
                    email="other-user@mobius.invalid",
                    display_name="Other user",
                    session_id=None,
                    csrf_token_hash=None,
                    synthetic=True,
                ),
                workspace_id=workspace_a,
                canvas_id=canvas_a,
                session_id=view.session.session_id,
            )
        with pytest.raises(ObjectIngestionNotFoundError):
            await service.upload_bytes(
                session_id=view.session.session_id,
                capability=f"{view.capability}x",
                content=content,
            )
        with pytest.raises(ObjectIngestionError, match="do not match"):
            await service.upload_bytes(
                session_id=view.session.session_id,
                capability=view.capability,
                content=b"substituted bytes",
            )
        assert await session.scalar(select(func.count()).select_from(StorageObjectVersion)) == 0


@pytest.mark.asyncio
async def test_pending_object_cannot_parse_download_or_enter_indexer(
    database: Database,
    tmp_path: Path,
) -> None:
    settings, storage, workspace_id, canvas_id, completed = await _completed_upload(
        database,
        tmp_path,
        content=b"pending bytes remain quarantined",
    )
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DocumentChunk)) == 0
        assert await session.scalar(select(func.count()).select_from(ObjectPromotion)) == 0
        with pytest.raises(ObjectIngestionNotFoundError):
            await UploadLifecycleService(
                session,
                settings=settings,
                storage=storage,
            ).clean_bytes(
                principal=_principal(),
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                session_id=completed.session.session_id,
            )
        with pytest.raises(IndexerError) as exc_info:
            await IngestionService(
                session,
                settings=settings,
                storage=MemoryDocumentStorage(),
                provider=MockEmbeddingProvider(),
            ).request(
                principal=_principal(),
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                document_id=completed.session.document_id,
                document_version=1,
                idempotency_key="pending-index-request",
            )
        assert exc_info.value.code == "source_not_clean"
        assert await session.scalar(select(func.count()).select_from(ObjectPromotion)) == 0


@pytest.mark.asyncio
async def test_timeout_reconciliation_and_deletion_request_block_reads(
    database: Database,
    tmp_path: Path,
) -> None:
    settings, _storage, _workspace_id, _canvas_id, completed = await _completed_upload(
        database, tmp_path
    )
    assert completed.scan_request is not None
    async with database.sessions() as session:
        request = await session.get(MalwareScanRequest, completed.scan_request.scan_request_id)
        assert request is not None
        expired = await ObjectReconciler(session, settings=settings).expire_scan_requests(
            now=request.deadline_at + timedelta(seconds=1)
        )
        assert expired == 1
        latest = await session.scalar(
            select(StorageObjectLifecycleTransition)
            .where(
                StorageObjectLifecycleTransition.object_version_id
                == completed.session.object_version_id
            )
            .order_by(StorageObjectLifecycleTransition.sequence.desc())
            .limit(1)
        )
        assert latest is not None and latest.current_state == "error"

    settings_2, storage_2, workspace_2, canvas_2, completed_2 = await _completed_upload(
        database,
        tmp_path,
        content=b"delete after clean",
    )
    clean_result = await _bind_result(database, completed_2, _scan_result(completed_2))
    async with database.sessions() as session:
        await MalwareScanService(
            session,
            settings=settings_2,
            storage=storage_2,
        ).record_result(
            result=clean_result,
            signature=scanner_result_signature(
                clean_result,
                settings_2.scanner_result_secret,
            ),
        )
        lifecycle = UploadLifecycleService(
            session,
            settings=settings_2,
            storage=storage_2,
        )
        deleted = await lifecycle.request_deletion(
            principal=_principal(),
            workspace_id=workspace_2,
            canvas_id=canvas_2,
            session_id=completed_2.session.session_id,
            idempotency_key="delete-clean-object",
            reason_code="user_requested",
        )
        assert deleted.object_transition is not None
        assert deleted.object_transition.current_state == "deletion_requested"
        with pytest.raises(ObjectIngestionNotFoundError):
            await lifecycle.clean_bytes(
                principal=_principal(),
                workspace_id=workspace_2,
                canvas_id=canvas_2,
                session_id=completed_2.session.session_id,
            )
        assert await session.scalar(select(func.count()).select_from(ObjectDeletionRequest)) == 1


@pytest.mark.asyncio
async def test_memory_provider_is_versioned_private_and_idempotent() -> None:
    storage = MemoryVersionedObjectStorage()
    object_id = uuid.uuid4()
    object_version_id = uuid.uuid4()
    content = b"provider contract"
    digest = hashlib.sha256(content).hexdigest()
    first = await storage.put_immutable(
        security_class="quarantine",
        object_id=object_id,
        object_version_id=object_version_id,
        content=content,
        expected_sha256=digest,
    )
    duplicate = await storage.put_immutable(
        security_class="quarantine",
        object_id=object_id,
        object_version_id=object_version_id,
        content=content,
        expected_sha256=digest,
    )
    assert duplicate == first
    assert (
        await storage.read_version(
            physical_key=first.physical_key,
            provider_version_id=first.provider_version_id,
        )
        == content
    )
    with pytest.raises(DocumentStorageError):
        await storage.put_immutable(
            security_class="quarantine",
            object_id=object_id,
            object_version_id=object_version_id,
            content=b"different",
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
        )


def test_active_content_and_nested_container_controls(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(DocumentValidationError, match="active content"):
        validate_document_bytes(
            filename="active.pdf",
            content=(
                b"%PDF-1.4\n1 0 obj <</Type /Catalog /OpenAction 2 0 R>> endobj\n"
                b"2 0 obj <</S /JavaScript /JS (alert)>> endobj\n%%EOF"
            ),
            declared_media_type="application/pdf",
            settings=settings,
        )


@pytest.mark.asyncio
async def test_secure_upload_api_uses_one_scoped_store_through_clean_download(
    app: FastAPI,
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app.dependency_overrides[get_settings] = lambda: settings
    if hasattr(app.state, "versioned_object_storage"):
        del app.state.versioned_object_storage
    canvas = await _create_canvas(client, api_prefix, "Secure upload API")
    workspace_id = uuid.UUID(cast(str, canvas["workspaceId"]))
    canvas_id = uuid.UUID(cast(str, canvas["id"]))
    await _register_canvas_resource(
        database,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
    )
    content = b"api clean-object evidence"
    digest = hashlib.sha256(content).hexdigest()
    initiated = await client.post(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions",
        json={
            "fileName": "api.txt",
            "mediaType": "text/plain",
            "sizeBytes": len(content),
            "sha256": digest,
            "idempotencyKey": "secure-api-upload",
        },
    )
    assert initiated.status_code == 201, initiated.text
    payload = initiated.json()
    uploaded = await client.put(
        payload["uploadPath"],
        content=content,
        headers={"X-Upload-Capability": payload["capability"]},
    )
    assert uploaded.status_code == 200, uploaded.text
    completed = await client.post(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/upload-sessions/{payload['sessionId']}/complete"
    )
    assert completed.status_code == 200, completed.text

    async with database.sessions() as session:
        request = await session.scalar(
            select(MalwareScanRequest).where(
                MalwareScanRequest.object_version_id
                == uuid.UUID(cast(str, payload["objectVersionId"]))
            )
        )
        version = await session.get(
            StorageObjectVersion,
            uuid.UUID(cast(str, payload["objectVersionId"])),
        )
        assert request is not None and version is not None
    result = TrustedScanResult(
        scan_request_id=request.scan_request_id,
        object_version_id=version.object_version_id,
        workspace_id=workspace_id,
        outcome="clean",
        scanner_identity=request.scanner_identity,
        scanner_version=request.scanner_version,
        engine_version="engine-api-v1",
        signature_version="signatures-api-v1",
        policy_version=request.policy_version,
        provider_result_id=f"provider-{uuid.uuid4().hex}",
        provider_record_digest=hashlib.sha256(b"api-provider-record").hexdigest(),
        provider_version_id=version.provider_version_id,
        etag=version.etag,
        content_sha256=version.content_sha256,
        scanned_at=datetime.now(UTC),
        safe_reason_code="no_threats_found",
    )
    scan = await client.post(
        f"{api_prefix}/internal/object-ingestion/scan-results",
        headers={
            "X-Scanner-Result-Signature": scanner_result_signature(
                result,
                settings.scanner_result_secret,
            )
        },
        json={
            "scanRequestId": str(result.scan_request_id),
            "objectVersionId": str(result.object_version_id),
            "workspaceId": str(result.workspace_id),
            "outcome": result.outcome,
            "scannerIdentity": result.scanner_identity,
            "scannerVersion": result.scanner_version,
            "engineVersion": result.engine_version,
            "signatureVersion": result.signature_version,
            "policyVersion": result.policy_version,
            "providerResultId": result.provider_result_id,
            "providerRecordDigest": result.provider_record_digest,
            "providerVersionId": result.provider_version_id,
            "etag": result.etag,
            "contentSha256": result.content_sha256,
            "scannedAt": result.scanned_at.isoformat(),
            "safeReasonCode": result.safe_reason_code,
        },
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["objectState"] == "clean"
    download = await client.get(
        f"{api_prefix}/workspaces/{workspace_id}/canvases/{canvas_id}"
        f"/upload-sessions/{payload['sessionId']}/file"
    )
    assert download.status_code == 200
    assert download.content == content
