from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    enforce_document_rate_limit,
    enforce_scanner_result_rate_limit,
    get_database,
    get_session,
    get_versioned_object_storage,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import (
    DocumentMetadata,
    DocumentSearchMatch,
    DocumentSearchOut,
    DocumentSearchRequest,
    DocumentTextOut,
    DocumentTextSection,
    SecureObjectDeletionCreate,
    SecureUploadCreate,
    SecureUploadOut,
    SourcePassageOut,
    TrustedScanResultIn,
    UploadDocumentOut,
)
from opencanvas_api.api.serialization import (
    document_metadata_out,
    node_out,
    source_passage_out,
)
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    Canvas,
    CanvasDocumentNode,
    CanvasNode,
    Document,
    DocumentChunk,
    DocumentFile,
    DocumentVersion,
    UploadSession,
    UsageRecord,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.authorization import (
    AuthorizationError,
    require_owned_canvas,
    require_owned_document,
)
from opencanvas_api.services.documents import (
    DocumentProcessor,
    DocumentServiceError,
    RetrievedChunk,
    VersionedObjectStorage,
    build_document_storage,
    build_embedding_provider,
    delete_document,
    replace_document_upload,
    search_documents,
    validate_and_store_upload,
)
from opencanvas_api.services.jobs import JobQueueError, build_job_provider
from opencanvas_api.services.object_ingestion import (
    MalwareScanService,
    ObjectIngestionError,
    TrustedScanResult,
    UploadLifecycleService,
    UploadSessionView,
)

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
ObjectStorageDep = Annotated[
    VersionedObjectStorage,
    Depends(get_versioned_object_storage),
]
CanvasCoordinate = Annotated[float, Form(ge=-1_000_000, le=1_000_000)]


def _service_error(error: DocumentServiceError) -> ApiError:
    return ApiError(error.status_code, error.code, error.safe_message)


def _ingestion_error(error: ObjectIngestionError) -> ApiError:
    return ApiError(error.status_code, error.code, error.safe_message)


def _secure_upload_out(view: UploadSessionView, *, api_prefix: str) -> SecureUploadOut:
    return SecureUploadOut(
        session_id=view.session.session_id,
        workspace_id=view.session.workspace_id,
        canvas_id=view.session.canvas_id,
        document_id=view.session.document_id,
        document_version_id=view.session.document_version_id,
        object_version_id=view.session.object_version_id,
        state=cast(
            Literal["requested", "uploaded", "completed", "canceled", "expired", "error"],
            view.transition.current_state,
        ),
        object_state=(
            cast(
                Literal[
                    "quarantined",
                    "scan_pending",
                    "clean",
                    "rejected",
                    "retained",
                    "deletion_requested",
                    "deleted",
                    "legacy_unscanned",
                    "canceled",
                    "error",
                ],
                view.object_transition.current_state,
            )
            if view.object_transition is not None
            else None
        ),
        scan_outcome=(
            cast(
                Literal["clean", "infected", "suspicious", "unsupported", "error", "timeout"],
                view.scan_result.outcome,
            )
            if view.scan_result is not None
            else None
        ),
        safe_reason_code=(
            view.scan_result.safe_reason_code if view.scan_result is not None else None
        ),
        capability=view.capability,
        upload_path=(
            f"{api_prefix}/upload-sessions/{view.session.session_id}/content"
            if view.capability
            else None
        ),
        expires_at=view.session.expires_at,
        duplicate=view.duplicate,
    )


def _ingestion_service(
    session: AsyncSession,
    settings: Settings,
    storage: VersionedObjectStorage,
) -> UploadLifecycleService:
    return UploadLifecycleService(
        session,
        settings=settings,
        storage=storage,
    )


async def _require_canvas(
    session: AsyncSession, canvas_id: uuid.UUID, principal: Principal
) -> Canvas:
    try:
        return await require_owned_canvas(session, principal, canvas_id)
    except AuthorizationError as exc:
        raise ApiError(status.HTTP_404_NOT_FOUND, "canvas_not_found", "Canvas not found.") from exc


async def _require_document(
    session: AsyncSession, document_id: uuid.UUID, principal: Principal
) -> Document:
    try:
        return await require_owned_document(session, principal, document_id)
    except AuthorizationError as exc:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "document_not_found", "Document not found."
        ) from exc


async def _bump_canvas(session: AsyncSession, canvas: Canvas) -> None:
    canvas.revision += 1
    session.add(canvas)
    await session.flush()


def _match_out(match: RetrievedChunk) -> DocumentSearchMatch:
    return DocumentSearchMatch(
        document_id=match.document_id,
        chunk_id=match.chunk_id,
        document_title=match.document_name,
        page_number=match.page_number,
        heading=match.heading,
        chunk_index=match.chunk_index,
        start_offset=match.char_start,
        end_offset=match.char_end,
        text=match.content,
        score=match.score,
    )


async def _persist_unexpected_processing_failure(
    database: Database, document_id: uuid.UUID
) -> None:
    async with database.sessions() as session:
        document = await session.get(Document, document_id)
        if document is None or document.status == "ready":
            return
        document.status = "failed"
        document.processing_stage = "failed"
        document.error_message = "The document could not be processed. Retry the upload."
        await session.commit()


async def _process_document_background(
    database: Database,
    settings: Settings,
    document_id: uuid.UUID,
    *,
    force: bool,
) -> None:
    try:
        processor = DocumentProcessor(
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )
        await processor.process(database.sessions, document_id, force=force)
    except DocumentServiceError:
        # DocumentProcessor commits its actionable failed state before surfacing the error.
        return
    except Exception:
        # Background exceptions must never escape the response lifecycle or leave a stuck job.
        await _persist_unexpected_processing_failure(database, document_id)


@router.post(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions",
    response_model=SecureUploadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def initiate_secure_upload(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: SecureUploadCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> SecureUploadOut:
    try:
        view = await _ingestion_service(session, settings, storage).initiate(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            file_name=payload.file_name,
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
            sha256=payload.sha256,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except (ObjectIngestionError, DocumentServiceError) as exc:
        await session.rollback()
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.put(
    "/upload-sessions/{session_id}/content",
    response_model=SecureUploadOut,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def upload_secure_content(
    session_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
    capability: Annotated[str, Header(alias="X-Upload-Capability", min_length=32)],
) -> SecureUploadOut:
    content = await request.body()
    if len(content) > settings.document_max_file_size_bytes:
        raise ApiError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "file_too_large",
            "The upload exceeds the configured file limit.",
        )
    try:
        view = await _ingestion_service(session, settings, storage).upload_bytes(
            session_id=session_id,
            capability=capability,
            content=content,
        )
        await session.commit()
    except (ObjectIngestionError, DocumentServiceError) as exc:
        await session.rollback()
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.post(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions/{session_id}/complete",
    response_model=SecureUploadOut,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def complete_secure_upload(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    session_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> SecureUploadOut:
    try:
        view = await _ingestion_service(session, settings, storage).complete(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        await session.commit()
    except (ObjectIngestionError, DocumentServiceError) as exc:
        await session.rollback()
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.get(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions/{session_id}",
    response_model=SecureUploadOut,
)
async def get_secure_upload(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    session_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> SecureUploadOut:
    try:
        view = await _ingestion_service(session, settings, storage).get(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
        )
    except (ObjectIngestionError, DocumentServiceError) as exc:
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.post(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions/{session_id}/cancel",
    response_model=SecureUploadOut,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def cancel_secure_upload(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    session_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> SecureUploadOut:
    try:
        view = await _ingestion_service(session, settings, storage).cancel(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        await session.commit()
    except (ObjectIngestionError, DocumentServiceError) as exc:
        await session.rollback()
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.post(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions/{session_id}/rescan",
    response_model=SecureUploadOut,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def rescan_secure_upload(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    session_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> SecureUploadOut:
    try:
        view = await _ingestion_service(session, settings, storage).request_rescan(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        await session.commit()
    except (ObjectIngestionError, DocumentServiceError) as exc:
        await session.rollback()
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.post(
    "/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions/{session_id}"
    "/deletion-requests",
    response_model=SecureUploadOut,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def request_secure_object_deletion(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: SecureObjectDeletionCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> SecureUploadOut:
    try:
        view = await _ingestion_service(session, settings, storage).request_deletion(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
            idempotency_key=payload.idempotency_key,
            reason_code=payload.reason_code,
        )
        await session.commit()
    except (ObjectIngestionError, DocumentServiceError) as exc:
        await session.rollback()
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.post(
    "/internal/object-ingestion/scan-results",
    response_model=SecureUploadOut,
    dependencies=[Depends(enforce_scanner_result_rate_limit)],
)
async def record_trusted_scan_result(
    payload: TrustedScanResultIn,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
    signature: Annotated[str, Header(alias="X-Scanner-Result-Signature", min_length=64)],
) -> SecureUploadOut:
    result = TrustedScanResult(
        scan_request_id=payload.scan_request_id,
        object_version_id=payload.object_version_id,
        workspace_id=payload.workspace_id,
        outcome=payload.outcome,
        scanner_identity=payload.scanner_identity,
        scanner_version=payload.scanner_version,
        engine_version=payload.engine_version,
        signature_version=payload.signature_version,
        policy_version=payload.policy_version,
        provider_result_id=payload.provider_result_id,
        provider_record_digest=payload.provider_record_digest.lower(),
        provider_version_id=payload.provider_version_id,
        etag=payload.etag,
        content_sha256=payload.content_sha256.lower(),
        scanned_at=payload.scanned_at,
        safe_reason_code=payload.safe_reason_code,
    )
    try:
        view = await MalwareScanService(
            session,
            settings=settings,
            storage=storage,
        ).record_result(result=result, signature=signature)
        await session.commit()
    except (ObjectIngestionError, DocumentServiceError) as exc:
        await session.rollback()
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return _secure_upload_out(view, api_prefix=settings.api_prefix)


@router.get("/workspaces/{workspace_id}/canvases/{canvas_id}/upload-sessions/{session_id}/file")
async def download_clean_upload(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    session_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> Response:
    try:
        record, version, content = await _ingestion_service(session, settings, storage).clean_bytes(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
        )
    except (ObjectIngestionError, DocumentServiceError) as exc:
        if isinstance(exc, ObjectIngestionError):
            raise _ingestion_error(exc) from exc
        raise _service_error(exc) from exc
    return Response(
        content=content,
        media_type=version.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(record.file_name)}",
            "Content-Length": str(len(content)),
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/canvases/{canvas_id}/documents",
    response_model=UploadDocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def upload_document(
    canvas_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF, TXT, Markdown, or DOCX document")],
    x: CanvasCoordinate = 80.0,
    y: CanvasCoordinate = 80.0,
) -> UploadDocumentOut:
    if settings.object_ingestion_mode != "disabled":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "secure_upload_required",
            "This environment requires the secure quarantine upload workflow.",
        )
    canvas = await _require_canvas(session, canvas_id, principal)
    storage = build_document_storage(settings)
    job_provider = build_job_provider(settings)
    try:
        document = await validate_and_store_upload(
            session,
            canvas_id=canvas_id,
            upload=file,
            settings=settings,
            storage=storage,
        )
    except DocumentServiceError as exc:
        await session.rollback()
        raise _service_error(exc) from exc

    storage_key = await session.scalar(
        select(DocumentFile.storage_key).where(DocumentFile.document_id == document.id)
    )
    try:
        node = CanvasNode(
            canvas_id=canvas_id,
            type="document",
            title=document.file_name[:160],
            text="",
            position_x=x,
            position_y=y,
            width=360,
            height=260,
        )
        session.add(node)
        await session.flush()
        session.add(
            CanvasDocumentNode(
                node_id=node.id,
                canvas_id=canvas_id,
                document_id=document.id,
            )
        )
        await job_provider.enqueue(
            session,
            user_id=principal.user_id,
            workspace_id=canvas.workspace_id,
            document=document,
        )
        session.add(
            UsageRecord(
                user_id=principal.user_id,
                workspace_id=canvas.workspace_id,
                operation="document_upload",
                storage_bytes=document.file_size_bytes,
                metadata_payload={
                    "documentId": str(document.id),
                    "contentSha256": document.content_sha256,
                },
            )
        )
        await _bump_canvas(session, canvas)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        if storage_key is not None:
            try:
                await storage.delete(storage_key)
            except DocumentServiceError as cleanup_error:
                raise _service_error(cleanup_error) from exc
        if isinstance(exc, JobQueueError):
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "processing_limit_reached",
                str(exc),
            ) from exc
        raise
    await session.refresh(document)
    await session.refresh(node)
    metadata = document_metadata_out(document)
    if job_provider.runs_inline:
        background_tasks.add_task(
            _process_document_background,
            database,
            settings,
            document.id,
            force=False,
        )
    return UploadDocumentOut(
        document=metadata,
        node=node_out(node, document=metadata),
    )


@router.get("/documents/{document_id}", response_model=DocumentMetadata)
async def get_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> DocumentMetadata:
    return document_metadata_out(await _require_document(session, document_id, principal))


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> Response:
    document = await _require_document(session, document_id, principal)
    if settings.object_ingestion_mode != "disabled":
        upload = await session.scalar(
            select(UploadSession).where(UploadSession.document_id == document_id)
        )
        if upload is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                "file_not_found",
                "Document file not found.",
            )
        try:
            _, version, content = await _ingestion_service(session, settings, storage).clean_bytes(
                principal=principal,
                workspace_id=upload.workspace_id,
                canvas_id=upload.canvas_id,
                session_id=upload.session_id,
            )
        except (ObjectIngestionError, DocumentServiceError) as exc:
            if isinstance(exc, ObjectIngestionError):
                raise _ingestion_error(exc) from exc
            raise _service_error(exc) from exc
        return Response(
            content=content,
            media_type=version.media_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.file_name)}",
                "Content-Length": str(len(content)),
                "Cache-Control": "private, no-store",
            },
        )
    stored_file = await session.scalar(
        select(DocumentFile).where(DocumentFile.document_id == document.id)
    )
    if stored_file is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "file_not_found", "Document file not found.")
    try:
        content = await build_document_storage(settings).read(stored_file.storage_key)
    except DocumentServiceError as exc:
        raise _service_error(exc) from exc
    return Response(
        content=content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.file_name)}",
            "Content-Length": str(len(content)),
        },
    )


@router.post(
    "/documents/{document_id}/replace",
    response_model=DocumentMetadata,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def replace_document(
    document_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Replacement document")],
) -> DocumentMetadata:
    if settings.object_ingestion_mode != "disabled":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "secure_upload_required",
            "This environment requires the secure quarantine upload workflow.",
        )
    document = await _require_document(session, document_id, principal)
    canvas = await _require_canvas(session, document.canvas_id, principal)
    storage = build_document_storage(settings)
    try:
        document, _ = await replace_document_upload(
            session,
            document=document,
            upload=file,
            settings=settings,
            storage=storage,
        )
        job_provider = build_job_provider(settings)
        await job_provider.enqueue(
            session,
            user_id=principal.user_id,
            workspace_id=canvas.workspace_id,
            document=document,
            force=True,
        )
        await _bump_canvas(session, canvas)
        await session.commit()
    except DocumentServiceError as exc:
        await session.rollback()
        raise _service_error(exc) from exc
    except JobQueueError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS, "processing_limit_reached", str(exc)
        ) from exc
    if job_provider.runs_inline:
        background_tasks.add_task(
            _process_document_background,
            database,
            settings,
            document.id,
            force=True,
        )
    await session.refresh(document)
    return document_metadata_out(document)


@router.get("/documents/{document_id}/text", response_model=DocumentTextOut)
async def get_document_text(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> DocumentTextOut:
    document = await _require_document(session, document_id, principal)
    if settings.object_ingestion_mode != "disabled":
        upload = await session.scalar(
            select(UploadSession).where(UploadSession.document_id == document_id)
        )
        if upload is None:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "document_not_clean",
                "The document has no current clean-object evidence.",
            )
        try:
            await _ingestion_service(session, settings, storage).clean_bytes(
                principal=principal,
                workspace_id=upload.workspace_id,
                canvas_id=upload.canvas_id,
                session_id=upload.session_id,
            )
        except (ObjectIngestionError, DocumentServiceError) as exc:
            if isinstance(exc, ObjectIngestionError):
                raise _ingestion_error(exc) from exc
            raise _service_error(exc) from exc
    if document.extracted_text is None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "document_text_unavailable",
            document.error_message or "Document text is not available until processing completes.",
        )
    chunks = (
        await session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index, DocumentChunk.id)
        )
    ).all()
    sections = [
        DocumentTextSection(
            page_number=chunk.page_number,
            heading=chunk.heading,
            start_offset=chunk.char_start,
            end_offset=chunk.char_end,
        )
        for chunk in chunks
    ]
    return DocumentTextOut(
        document_id=document.id,
        file_name=document.file_name,
        text=document.extracted_text,
        sections=sections,
    )


@router.get(
    "/documents/{document_id}/chunks/{chunk_id}",
    response_model=SourcePassageOut,
)
async def get_source_passage(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: ObjectStorageDep,
) -> SourcePassageOut:
    document = await _require_document(session, document_id, principal)
    if settings.object_ingestion_mode != "disabled":
        upload = await session.scalar(
            select(UploadSession).where(UploadSession.document_id == document_id)
        )
        if upload is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                "chunk_not_found",
                "Source passage not found.",
            )
        try:
            await _ingestion_service(session, settings, storage).clean_bytes(
                principal=principal,
                workspace_id=upload.workspace_id,
                canvas_id=upload.canvas_id,
                session_id=upload.session_id,
            )
        except (ObjectIngestionError, DocumentServiceError) as exc:
            if isinstance(exc, ObjectIngestionError):
                raise _ingestion_error(exc) from exc
            raise _service_error(exc) from exc
    chunk = await session.scalar(
        select(DocumentChunk).where(
            DocumentChunk.id == chunk_id,
            DocumentChunk.document_id == document_id,
        )
    )
    if chunk is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "chunk_not_found", "Source passage not found.")
    return source_passage_out(chunk, document)


@router.post(
    "/documents/{document_id}/retry",
    response_model=DocumentMetadata,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def retry_document_processing(
    document_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
) -> DocumentMetadata:
    document = await _require_document(session, document_id, principal)
    canvas = await _require_canvas(session, document.canvas_id, principal)
    if document.status not in {"failed", "retryable_failure", "permanent_failure"}:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "document_retry_not_allowed",
            "Only failed documents can be retried.",
        )
    job_provider = build_job_provider(settings)
    try:
        await job_provider.enqueue(
            session,
            user_id=principal.user_id,
            workspace_id=canvas.workspace_id,
            document=document,
            force=True,
        )
    except JobQueueError as exc:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "processing_limit_reached",
            str(exc),
        ) from exc
    await _bump_canvas(session, canvas)
    await session.commit()
    await session.refresh(document)
    metadata = document_metadata_out(document)
    if job_provider.runs_inline:
        background_tasks.add_task(
            _process_document_background,
            database,
            settings,
            document.id,
            force=True,
        )
    return metadata


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentMetadata,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def reprocess_document(
    document_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
) -> DocumentMetadata:
    document = await _require_document(session, document_id, principal)
    canvas = await _require_canvas(session, document.canvas_id, principal)
    if document.status != "ready":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "document_reprocess_not_allowed",
            "Only ready documents can be reprocessed.",
        )
    job_provider = build_job_provider(settings)
    try:
        await job_provider.enqueue(
            session,
            user_id=principal.user_id,
            workspace_id=canvas.workspace_id,
            document=document,
            force=True,
        )
    except JobQueueError as exc:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "processing_limit_reached",
            str(exc),
        ) from exc
    await _bump_canvas(session, canvas)
    await session.commit()
    if job_provider.runs_inline:
        background_tasks.add_task(
            _process_document_background,
            database,
            settings,
            document.id,
            force=True,
        )
    await session.refresh(document)
    return document_metadata_out(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    document_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    document = await _require_document(session, document_id, principal)
    canvas = await _require_canvas(session, document.canvas_id, principal)
    storage = build_document_storage(settings)
    version_storage_keys = set(
        (
            await session.scalars(
                select(DocumentVersion.storage_key).where(
                    DocumentVersion.document_id == document_id
                )
            )
        ).all()
    )
    try:
        storage_key = await delete_document(session, document_id=document_id)
        if storage_key is not None:
            version_storage_keys.add(storage_key)
        for version_storage_key in sorted(version_storage_keys):
            await storage.delete(version_storage_key)
    except DocumentServiceError as exc:
        await session.rollback()
        raise _service_error(exc) from exc
    await _bump_canvas(session, canvas)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/canvases/{canvas_id}/documents/search",
    response_model=DocumentSearchOut,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def search_selected_documents(
    canvas_id: uuid.UUID,
    payload: DocumentSearchRequest,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> DocumentSearchOut:
    await _require_canvas(session, canvas_id, principal)
    documents = (
        await session.scalars(
            select(Document).where(
                Document.canvas_id == canvas_id,
                Document.id.in_(payload.document_ids),
            )
        )
    ).all()
    if {document.id for document in documents} != set(payload.document_ids):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "invalid_selected_documents",
            "Every selected document must belong to this canvas.",
        )
    unavailable = [document.file_name for document in documents if document.status != "ready"]
    if unavailable:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "documents_not_ready",
            "Selected documents are still processing or failed. Retry them before searching.",
        )
    try:
        matches = await search_documents(
            session,
            document_ids=payload.document_ids,
            query=payload.query,
            provider=build_embedding_provider(settings),
            top_k=payload.top_k or settings.document_retrieval_top_k,
            threshold=(
                payload.min_relevance
                if payload.min_relevance is not None
                else settings.document_relevance_threshold
            ),
            settings=settings,
        )
    except DocumentServiceError as exc:
        raise _service_error(exc) from exc
    included_matches = [match for match in matches if match.included_in_context]
    return DocumentSearchOut(
        query=payload.query,
        matches=[_match_out(match) for match in included_matches],
        insufficient_context=not included_matches,
    )
