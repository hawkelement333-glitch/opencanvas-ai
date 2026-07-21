from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    Canvas,
    CanvasDocumentNode,
    CanvasNode,
    Document,
    DocumentChunk,
    DocumentEmbedding,
    DocumentFile,
    DocumentProcessingJob,
    DocumentVersion,
    Workspace,
)
from opencanvas_api.services.documents.chunking import chunk_document
from opencanvas_api.services.documents.embeddings import EmbeddingProvider
from opencanvas_api.services.documents.errors import (
    DocumentProcessingError,
    DocumentServiceError,
)
from opencanvas_api.services.documents.extraction import extract_document
from opencanvas_api.services.documents.storage import DocumentStorage
from opencanvas_api.services.documents.validation import (
    read_upload_limited,
    validate_document_bytes,
)


async def validate_and_store_upload(
    session: AsyncSession,
    *,
    canvas_id: uuid.UUID,
    upload: UploadFile,
    settings: Settings,
    storage: DocumentStorage,
) -> Document:
    content = await read_upload_limited(upload, settings.document_max_file_size_bytes)
    validated = await asyncio.to_thread(
        validate_document_bytes,
        filename=upload.filename,
        content=content,
        declared_media_type=upload.content_type,
        settings=settings,
    )
    duplicate = await session.scalar(
        select(Document.id).where(
            Document.canvas_id == canvas_id,
            Document.content_sha256 == validated.sha256,
            Document.deleted_at.is_(None),
            Document.status != "deleted",
        )
    )
    if duplicate is not None:
        raise DocumentProcessingError(
            "This exact file already exists in the workspace.",
            code="duplicate_upload",
            status_code=409,
        )
    document = Document(
        canvas_id=canvas_id,
        file_name=validated.file_name,
        file_type=validated.file_type,
        media_type=validated.media_type,
        file_size_bytes=validated.size_bytes,
        content_sha256=validated.sha256,
        status="processing",
        processing_stage="uploading",
        chunk_count=0,
    )
    session.add(document)
    await session.flush()
    stored = await storage.store(document.id, validated.extension, validated.content)
    session.add(
        DocumentFile(
            document_id=document.id,
            storage_key=stored.storage_key,
            byte_size=stored.byte_size,
            sha256=validated.sha256,
            media_type=validated.media_type,
        )
    )
    session.add(
        DocumentVersion(
            document_id=document.id,
            version=1,
            file_name=validated.file_name,
            file_type=validated.file_type,
            media_type=validated.media_type,
            file_size_bytes=validated.size_bytes,
            content_sha256=validated.sha256,
            storage_key=stored.storage_key,
            status="uploaded",
        )
    )
    try:
        await session.flush()
    except Exception:
        await storage.delete(stored.storage_key)
        raise
    return document


async def replace_document_upload(
    session: AsyncSession,
    *,
    document: Document,
    upload: UploadFile,
    settings: Settings,
    storage: DocumentStorage,
) -> tuple[Document, str]:
    content = await read_upload_limited(upload, settings.document_max_file_size_bytes)
    validated = await asyncio.to_thread(
        validate_document_bytes,
        filename=upload.filename,
        content=content,
        declared_media_type=upload.content_type,
        settings=settings,
    )
    if validated.sha256 == document.content_sha256:
        raise DocumentProcessingError(
            "The replacement is identical to the current document version.",
            code="duplicate_upload",
            status_code=409,
        )
    next_version = document.version_count + 1
    stored = await storage.store(document.id, validated.extension, validated.content)
    current_file = await session.scalar(
        select(DocumentFile).where(DocumentFile.document_id == document.id)
    )
    if current_file is None:
        await storage.delete(stored.storage_key)
        raise DocumentProcessingError("The current document file is missing.")
    previous_key = current_file.storage_key
    current_file.storage_key = stored.storage_key
    current_file.byte_size = stored.byte_size
    current_file.sha256 = validated.sha256
    current_file.media_type = validated.media_type
    session.add(
        DocumentVersion(
            document_id=document.id,
            version=next_version,
            file_name=validated.file_name,
            file_type=validated.file_type,
            media_type=validated.media_type,
            file_size_bytes=validated.size_bytes,
            content_sha256=validated.sha256,
            storage_key=stored.storage_key,
            status="uploaded",
        )
    )
    document.file_name = validated.file_name
    document.file_type = validated.file_type
    document.media_type = validated.media_type
    document.file_size_bytes = validated.size_bytes
    document.content_sha256 = validated.sha256
    document.status = "uploaded"
    document.processing_stage = "uploading"
    document.page_count = None
    document.chunk_count = 0
    document.extracted_text = None
    document.error_message = None
    document.safe_error_category = None
    document.version_count = next_version
    document.current_version = next_version
    await session.flush()
    return document, previous_key


INTERRUPTED_PROCESSING_MESSAGE = (
    "Document processing was interrupted by a server restart. Retry processing to continue."
)


async def reconcile_interrupted_processing(session: AsyncSession) -> None:
    """Atomically make abandoned in-process work retryable after a server restart."""
    now = datetime.now(UTC)
    active_stages = ("uploading", "extracting", "chunking", "embedding")
    await session.execute(
        update(Document)
        .where(Document.status == "processing")
        .values(
            status="failed",
            processing_stage="failed",
            error_message=INTERRUPTED_PROCESSING_MESSAGE,
            updated_at=now,
        )
    )
    await session.execute(
        update(DocumentProcessingJob)
        .where(DocumentProcessingJob.status.in_(active_stages))
        .values(
            status="failed",
            error_message=INTERRUPTED_PROCESSING_MESSAGE,
            completed_at=now,
            updated_at=now,
        )
    )
    await session.commit()


class DocumentProcessor:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: DocumentStorage,
        provider: EmbeddingProvider,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.provider = provider

    async def process(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        document_id: uuid.UUID,
        *,
        force: bool = False,
    ) -> Document:
        async with session_factory() as session:
            return await self._process(session, document_id, force=force, commit_stages=True)

    async def process_with_session(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        *,
        force: bool = False,
    ) -> Document:
        return await self._process(session, document_id, force=force, commit_stages=False)

    async def _process(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        *,
        force: bool,
        commit_stages: bool,
    ) -> Document:
        document = await session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if document is None:
            raise DocumentProcessingError(
                "The document does not exist.", code="document_not_found", status_code=404
            )
        if document.status == "ready" and not force:
            embedding_count = await session.scalar(
                select(func.count(DocumentEmbedding.id)).where(
                    DocumentEmbedding.document_id == document_id
                )
            )
            if document.chunk_count > 0 and embedding_count == document.chunk_count:
                return document
            force = True
        if document.status == "processing" and document.processing_stage not in {
            "uploading",
            "queued",
            "processing",
            "retrying",
        }:
            raise DocumentProcessingError(
                "The document is already being processed.",
                code="document_processing",
                status_code=409,
            )

        document_file = await session.scalar(
            select(DocumentFile).where(DocumentFile.document_id == document_id)
        )
        if document_file is None:
            raise DocumentProcessingError("The stored document file is missing.")
        canvas = await session.get(Canvas, document.canvas_id)
        workspace = (
            await session.get(Workspace, canvas.workspace_id) if canvas is not None else None
        )
        if canvas is None or workspace is None:
            raise DocumentProcessingError("The document workspace is unavailable.")
        job = await session.scalar(
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.document_id == document_id,
                DocumentProcessingJob.status.in_(("queued", "retrying", "processing")),
                DocumentProcessingJob.completed_at.is_(None),
            )
            .order_by(DocumentProcessingJob.attempt.desc())
            .limit(1)
            .with_for_update()
        )
        if job is None:
            attempt = (
                await session.scalar(
                    select(func.coalesce(func.max(DocumentProcessingJob.attempt), 0)).where(
                        DocumentProcessingJob.document_id == document_id
                    )
                )
                or 0
            ) + 1
            job = DocumentProcessingJob(
                user_id=workspace.owner_id,
                workspace_id=workspace.id,
                document_id=document_id,
                attempt=attempt,
                status="extracting",
                idempotency_key=(
                    f"document:{document_id}:version:{document.current_version}:attempt:{attempt}"
                ),
                started_at=datetime.now(UTC),
            )
            session.add(job)
        else:
            attempt = job.attempt
            job.status = "extracting"
            job.started_at = job.started_at or datetime.now(UTC)
        document.status = "processing"
        document.processing_stage = "extracting"
        document.error_message = None
        await self._persist(session, commit=commit_stages)
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version == document.current_version,
            )
        )

        try:
            content = await self.storage.read(document_file.storage_key)
            extracted = await asyncio.to_thread(
                extract_document,
                file_type=document.file_type,
                content=content,
                settings=self.settings,
            )
            document.extracted_text = extracted.text
            document.page_count = extracted.page_count
            if version is not None:
                version.extracted_text = extracted.text
                version.status = "processing"
            document.processing_stage = "chunking"
            job.status = "chunking"
            await self._persist(session, commit=commit_stages)

            chunks = chunk_document(
                extracted,
                chunk_size=self.settings.document_chunk_size_chars,
                overlap=self.settings.document_chunk_overlap_chars,
            )
            if not chunks:
                raise DocumentProcessingError(
                    "No searchable passages could be created.", status_code=422
                )
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            chunk_records = [
                DocumentChunk(
                    document_id=document_id,
                    document_version=document.current_version,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    heading=chunk.heading,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                )
                for chunk in chunks
            ]
            session.add_all(chunk_records)
            await session.flush()
            document.chunk_count = len(chunk_records)
            document.processing_stage = "embedding"
            job.status = "embedding"
            await self._persist(session, commit=commit_stages)

            vectors = await self.provider.embed([chunk.content for chunk in chunk_records])
            if len(vectors) != len(chunk_records):
                raise DocumentProcessingError(
                    "Embedding generation returned an incomplete result.",
                    code="embedding_failed",
                    status_code=502,
                )
            session.add_all(
                DocumentEmbedding(
                    document_id=document_id,
                    chunk_id=chunk.id,
                    provider=self.provider.name,
                    model=self.provider.model,
                    dimensions=self.provider.dimensions,
                    embedding=vector,
                )
                for chunk, vector in zip(chunk_records, vectors, strict=True)
            )
            document.status = "ready"
            document.processing_stage = "ready"
            document.error_message = None
            job.status = "ready"
            job.completed_at = datetime.now(UTC)
            if version is not None:
                version.status = "ready"
            await self._persist(session, commit=commit_stages)
            return document
        except Exception as exc:
            safe_message = (
                exc.safe_message
                if isinstance(exc, DocumentServiceError)
                else "The document could not be processed."
            )
            document.status = "failed"
            document.processing_stage = "failed"
            document.error_message = safe_message[:2_000]
            document.safe_error_category = (
                exc.code if isinstance(exc, DocumentServiceError) else "processing_failed"
            )
            document.retry_count = max(0, attempt - 1)
            job.status = "failed"
            job.error_message = safe_message[:2_000]
            job.safe_error_category = document.safe_error_category
            job.retryable = attempt <= self.settings.processing_retry_limit
            if version is not None:
                version.status = "failed"
            job.completed_at = datetime.now(UTC)
            await self._persist(session, commit=commit_stages)
            if isinstance(exc, DocumentProcessingError):
                raise
            if isinstance(exc, DocumentServiceError):
                raise DocumentProcessingError(
                    safe_message, code=exc.code, status_code=exc.status_code
                ) from exc
            raise DocumentProcessingError(safe_message, status_code=500) from exc

    @staticmethod
    async def _persist(session: AsyncSession, *, commit: bool) -> None:
        if commit:
            await session.commit()
        else:
            await session.flush()


async def retry_document(
    processor: DocumentProcessor, session: AsyncSession, document_id: uuid.UUID
) -> Document:
    return await processor.process_with_session(session, document_id, force=True)


async def delete_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
) -> str | None:
    document = await session.get(Document, document_id)
    if document is None:
        raise DocumentProcessingError(
            "The document does not exist.", code="document_not_found", status_code=404
        )
    storage_key = await session.scalar(
        select(DocumentFile.storage_key).where(DocumentFile.document_id == document_id)
    )
    node_ids = list(
        (
            await session.scalars(
                select(CanvasDocumentNode.node_id).where(
                    CanvasDocumentNode.document_id == document_id
                )
            )
        ).all()
    )
    if node_ids:
        await session.execute(delete(CanvasNode).where(CanvasNode.id.in_(node_ids)))
    await session.delete(document)
    await session.flush()
    return storage_key
