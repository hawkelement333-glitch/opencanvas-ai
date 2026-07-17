from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    enforce_document_rate_limit,
    get_database,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import (
    DocumentMetadata,
    DocumentSearchMatch,
    DocumentSearchOut,
    DocumentSearchRequest,
    DocumentTextOut,
    DocumentTextSection,
    SourcePassageOut,
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
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.documents import (
    DocumentProcessor,
    DocumentServiceError,
    RetrievedChunk,
    build_document_storage,
    build_embedding_provider,
    delete_document,
    search_documents,
    validate_and_store_upload,
)

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
CanvasCoordinate = Annotated[float, Form(ge=-1_000_000, le=1_000_000)]


def _service_error(error: DocumentServiceError) -> ApiError:
    return ApiError(error.status_code, error.code, error.safe_message)


async def _require_canvas(session: AsyncSession, canvas_id: uuid.UUID) -> Canvas:
    canvas = await session.get(Canvas, canvas_id)
    if canvas is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "canvas_not_found", "Canvas not found.")
    return canvas


async def _require_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "document_not_found", "Document not found.")
    return document


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
    "/canvases/{canvas_id}/documents",
    response_model=UploadDocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def upload_document(
    canvas_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF, TXT, Markdown, or DOCX document")],
    x: CanvasCoordinate = 80.0,
    y: CanvasCoordinate = 80.0,
) -> UploadDocumentOut:
    canvas = await _require_canvas(session, canvas_id)
    storage = build_document_storage(settings)
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
        await _bump_canvas(session, canvas)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        if storage_key is not None:
            try:
                await storage.delete(storage_key)
            except DocumentServiceError as cleanup_error:
                raise _service_error(cleanup_error) from exc
        raise
    await session.refresh(document)
    await session.refresh(node)
    metadata = document_metadata_out(document)
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
async def get_document(document_id: uuid.UUID, session: SessionDep) -> DocumentMetadata:
    return document_metadata_out(await _require_document(session, document_id))


@router.get("/documents/{document_id}/text", response_model=DocumentTextOut)
async def get_document_text(document_id: uuid.UUID, session: SessionDep) -> DocumentTextOut:
    document = await _require_document(session, document_id)
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
    session: SessionDep,
) -> SourcePassageOut:
    document = await _require_document(session, document_id)
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
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
) -> DocumentMetadata:
    document = await _require_document(session, document_id)
    canvas = await _require_canvas(session, document.canvas_id)
    if document.status != "failed":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "document_retry_not_allowed",
            "Only failed documents can be retried.",
        )
    document.status = "processing"
    document.processing_stage = "uploading"
    document.error_message = None
    await _bump_canvas(session, canvas)
    await session.commit()
    await session.refresh(document)
    metadata = document_metadata_out(document)
    background_tasks.add_task(
        _process_document_background,
        database,
        settings,
        document.id,
        force=True,
    )
    return metadata


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    document_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    document = await _require_document(session, document_id)
    canvas = await _require_canvas(session, document.canvas_id)
    storage = build_document_storage(settings)
    try:
        storage_key = await delete_document(session, document_id=document_id)
        if storage_key is not None:
            await storage.delete(storage_key)
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
    session: SessionDep,
    settings: SettingsDep,
) -> DocumentSearchOut:
    await _require_canvas(session, canvas_id)
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
        )
    except DocumentServiceError as exc:
        raise _service_error(exc) from exc
    included_matches = [match for match in matches if match.included_in_context]
    return DocumentSearchOut(
        query=payload.query,
        matches=[_match_out(match) for match in included_matches],
        insufficient_context=not included_matches,
    )
