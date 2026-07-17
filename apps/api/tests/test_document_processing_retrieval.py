from __future__ import annotations

import io
import math
import uuid
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

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
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.documents import (
    DocumentProcessingError,
    DocumentProcessor,
    DocumentStorageError,
    EmbeddingProviderError,
    LocalDocumentStorage,
    MockEmbeddingProvider,
    delete_document,
    reconcile_interrupted_processing,
    search_documents,
    validate_and_store_upload,
)


class FailingEmbeddingProvider:
    name = "mock"
    model = "mock-failure-v1"
    dimensions = 1536
    mock = True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise EmbeddingProviderError("The test embedding provider failed.")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        document_storage_root=tmp_path / "documents",
        document_chunk_size_chars=256,
        document_chunk_overlap_chars=32,
        document_retrieval_top_k=4,
        document_relevance_threshold=0.2,
        embedding_provider="mock",
    )


def _upload(filename: str, content: str, media_type: str = "text/markdown") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content.encode()),
        filename=filename,
        headers=Headers({"content-type": media_type}),
    )


async def _create_canvas(session: AsyncSession) -> Canvas:
    canvas = Canvas(name="Document test canvas")
    session.add(canvas)
    await session.flush()
    return canvas


async def _store_document(
    session: AsyncSession,
    *,
    canvas_id: uuid.UUID,
    filename: str,
    content: str,
    settings: Settings,
    storage: LocalDocumentStorage,
) -> Document:
    return await validate_and_store_upload(
        session,
        canvas_id=canvas_id,
        upload=_upload(filename, content),
        settings=settings,
        storage=storage,
    )


@pytest.mark.asyncio
async def test_processing_persists_embeddings_and_is_idempotent(
    database: Database, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_root)
    provider = MockEmbeddingProvider()
    processor = DocumentProcessor(settings=settings, storage=storage, provider=provider)
    async with database.sessions() as session:
        canvas = await _create_canvas(session)
        document = await _store_document(
            session,
            canvas_id=canvas.id,
            filename="aurora.md",
            content=(
                "# Launch\n\nThe launch codename is Aurora Finch. The pilot began on 14 April 2026."
            ),
            settings=settings,
            storage=storage,
        )
        await session.commit()

        processed = await processor.process_with_session(session, document.id)
        await session.commit()
        chunk_count = await session.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document.id)
        )
        embedding_count = await session.scalar(
            select(func.count(DocumentEmbedding.id)).where(
                DocumentEmbedding.document_id == document.id
            )
        )
        assert processed.status == "ready"
        assert chunk_count == processed.chunk_count == embedding_count
        assert embedding_count and embedding_count > 0

        await processor.process_with_session(session, document.id)
        await session.commit()
        second_chunk_count = await session.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document.id)
        )
        job_count = await session.scalar(
            select(func.count(DocumentProcessingJob.id)).where(
                DocumentProcessingJob.document_id == document.id
            )
        )
        assert second_chunk_count == chunk_count
        assert job_count == 1


@pytest.mark.asyncio
async def test_vector_retrieval_is_selected_document_scoped_and_thresholded(
    database: Database, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_root)
    provider = MockEmbeddingProvider()
    processor = DocumentProcessor(settings=settings, storage=storage, provider=provider)
    async with database.sessions() as session:
        canvas = await _create_canvas(session)
        fact_document = await _store_document(
            session,
            canvas_id=canvas.id,
            filename="aurora.md",
            content=(
                "# Launch\n\nThe launch codename is Aurora Finch. The pilot began on 14 April 2026."
            ),
            settings=settings,
            storage=storage,
        )
        pricing_document = await _store_document(
            session,
            canvas_id=canvas.id,
            filename="pricing.md",
            content="# Pricing\n\nThe pilot annual subscription price is forty-nine dollars.",
            settings=settings,
            storage=storage,
        )
        await session.commit()
        await processor.process_with_session(session, fact_document.id)
        await processor.process_with_session(session, pricing_document.id)
        await session.commit()

        supported = await search_documents(
            session,
            document_ids=[fact_document.id],
            query="What is the launch codename?",
            provider=provider,
            top_k=4,
            threshold=0.2,
        )
        assert supported
        assert all(result.document_id == fact_document.id for result in supported)
        assert supported[0].rank == 1
        assert supported[0].included_in_context is True
        assert supported[0].exclusion_reason is None

        unsupported = await search_documents(
            session,
            document_ids=[fact_document.id],
            query="What is the annual subscription price?",
            provider=provider,
            top_k=4,
            threshold=0.2,
        )
        assert unsupported
        assert all(result.document_id == fact_document.id for result in unsupported)
        assert not any(result.included_in_context for result in unsupported)
        assert unsupported[0].exclusion_reason == "below_relevance_threshold"

        both = await search_documents(
            session,
            document_ids=[fact_document.id, pricing_document.id],
            query="What is the annual subscription price?",
            provider=provider,
            top_k=1,
            threshold=0.2,
        )
        assert both[0].document_id == pricing_document.id
        assert both[0].included_in_context is True
        limited = await search_documents(
            session,
            document_ids=[fact_document.id, pricing_document.id],
            query="Tell me about the pilot.",
            provider=provider,
            top_k=1,
            threshold=0.05,
        )
        assert limited[0].included_in_context is True
        assert any(item.exclusion_reason == "top_k_limit" for item in limited[1:])


@pytest.mark.asyncio
async def test_processing_failure_can_be_retried_without_duplicate_chunks(
    database: Database, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_root)
    async with database.sessions() as session:
        canvas = await _create_canvas(session)
        document = await _store_document(
            session,
            canvas_id=canvas.id,
            filename="retry.md",
            content="# Retry\n\nA valid document can be retried after an embedding outage.",
            settings=settings,
            storage=storage,
        )
        await session.commit()
        failing = DocumentProcessor(
            settings=settings, storage=storage, provider=FailingEmbeddingProvider()
        )
        with pytest.raises(DocumentProcessingError, match="test embedding provider failed"):
            await failing.process_with_session(session, document.id)
        await session.commit()
        assert document.status == "failed"

        working = DocumentProcessor(
            settings=settings, storage=storage, provider=MockEmbeddingProvider()
        )
        retried = await working.process_with_session(session, document.id, force=True)
        await session.commit()
        chunk_count = await session.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document.id)
        )
        job_count = await session.scalar(
            select(func.count(DocumentProcessingJob.id)).where(
                DocumentProcessingJob.document_id == document.id
            )
        )
        assert retried.status == "ready"
        assert chunk_count == retried.chunk_count
        assert job_count == 2


@pytest.mark.asyncio
async def test_processing_guard_rejects_a_duplicate_in_flight_run(
    database: Database, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_root)
    processor = DocumentProcessor(
        settings=settings, storage=storage, provider=MockEmbeddingProvider()
    )
    async with database.sessions() as session:
        canvas = await _create_canvas(session)
        document = await _store_document(
            session,
            canvas_id=canvas.id,
            filename="busy.md",
            content="# Busy\n\nProcessing is already underway.",
            settings=settings,
            storage=storage,
        )
        document.processing_stage = "extracting"
        await session.commit()
        with pytest.raises(DocumentProcessingError, match="already being processed"):
            await processor.process_with_session(session, document.id, force=True)


@pytest.mark.asyncio
async def test_startup_reconciliation_makes_interrupted_processing_retryable(
    database: Database, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_root)
    async with database.sessions() as session:
        canvas = await _create_canvas(session)
        document = await _store_document(
            session,
            canvas_id=canvas.id,
            filename="interrupted.md",
            content="# Interrupted\n\nThis job was active when the process stopped.",
            settings=settings,
            storage=storage,
        )
        document.processing_stage = "embedding"
        job = DocumentProcessingJob(
            document_id=document.id,
            attempt=1,
            status="embedding",
        )
        session.add(job)
        await session.commit()

        await reconcile_interrupted_processing(session)
        await session.refresh(document)
        await session.refresh(job)

        assert document.status == "failed"
        assert document.processing_stage == "failed"
        assert document.error_message is not None and "interrupted" in document.error_message
        assert job.status == "failed"
        assert job.error_message == document.error_message
        assert job.completed_at is not None


@pytest.mark.asyncio
async def test_document_deletion_cleans_database_then_physical_storage(
    database: Database, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalDocumentStorage(settings.document_storage_root)
    processor = DocumentProcessor(
        settings=settings, storage=storage, provider=MockEmbeddingProvider()
    )
    async with database.sessions() as session:
        canvas = await _create_canvas(session)
        document = await _store_document(
            session,
            canvas_id=canvas.id,
            filename="delete.md",
            content="# Delete\n\nThis source will be removed completely.",
            settings=settings,
            storage=storage,
        )
        node = CanvasNode(
            canvas_id=canvas.id,
            type="document",
            title=document.file_name,
            text="",
            position_x=0,
            position_y=0,
        )
        session.add(node)
        await session.flush()
        session.add(
            CanvasDocumentNode(node_id=node.id, canvas_id=canvas.id, document_id=document.id)
        )
        await session.commit()
        await processor.process_with_session(session, document.id)
        await session.commit()
        stored_file = await session.scalar(
            select(DocumentFile).where(DocumentFile.document_id == document.id)
        )
        assert stored_file is not None
        assert await storage.read(stored_file.storage_key)

        storage_key = await delete_document(session, document_id=document.id)
        await session.commit()
        assert storage_key == stored_file.storage_key
        await storage.delete(storage_key)
        assert await session.get(Document, document.id) is None
        assert await session.get(CanvasNode, node.id) is None
        with pytest.raises(DocumentStorageError):
            await storage.read(storage_key)


@pytest.mark.asyncio
async def test_mock_embeddings_are_deterministic_and_normalized() -> None:
    provider = MockEmbeddingProvider()
    first, second = await provider.embed(["Aurora Finch launch", "Aurora Finch launch"])
    assert first == second
    assert len(first) == 1536
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)
