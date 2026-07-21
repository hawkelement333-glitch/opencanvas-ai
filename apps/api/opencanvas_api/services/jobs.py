from __future__ import annotations

import asyncio
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    Document,
    DocumentProcessingJob,
    WorkerHeartbeat,
)
from opencanvas_api.services.documents import (
    DocumentProcessingError,
    DocumentProcessor,
    build_document_storage,
    build_embedding_provider,
)

ACTIVE_JOB_STATUSES = ("queued", "retrying", "processing", "extracting", "chunking", "embedding")


class JobQueueError(RuntimeError):
    pass


class JobProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def runs_inline(self) -> bool: ...

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        document: Document,
        force: bool = False,
    ) -> DocumentProcessingJob: ...


@dataclass(frozen=True, slots=True)
class DatabaseJobProvider:
    settings: Settings
    name: str = "database"
    runs_inline: bool = False

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        document: Document,
        force: bool = False,
    ) -> DocumentProcessingJob:
        return await enqueue_document_job(
            session,
            settings=self.settings,
            user_id=user_id,
            workspace_id=workspace_id,
            document=document,
            force=force,
        )


@dataclass(frozen=True, slots=True)
class InlineJobProvider(DatabaseJobProvider):
    name: str = "inline"
    runs_inline: bool = True


async def enqueue_document_job(
    session: AsyncSession,
    *,
    settings: Settings,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    document: Document,
    force: bool,
) -> DocumentProcessingJob:
    if document.deleted_at is not None or document.status in {"deleting", "deleted"}:
        raise JobQueueError("A deleted document cannot be queued.")
    existing = await session.scalar(
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.document_id == document.id,
            DocumentProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(DocumentProcessingJob.attempt.desc())
        .limit(1)
    )
    if existing is not None and not force:
        return existing
    active_count = (
        await session.scalar(
            select(func.count(DocumentProcessingJob.id)).where(
                DocumentProcessingJob.workspace_id == workspace_id,
                DocumentProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        or 0
    )
    if active_count >= settings.processing_max_concurrent_per_workspace:
        raise JobQueueError("The workspace has reached its concurrent processing-job limit.")
    attempt = (
        await session.scalar(
            select(func.coalesce(func.max(DocumentProcessingJob.attempt), 0)).where(
                DocumentProcessingJob.document_id == document.id
            )
        )
        or 0
    ) + 1
    job = DocumentProcessingJob(
        user_id=user_id,
        workspace_id=workspace_id,
        document_id=document.id,
        attempt=attempt,
        status="queued" if attempt == 1 else "retrying",
        available_at=datetime.now(UTC),
        idempotency_key=(
            f"document:{document.id}:version:{document.current_version}:attempt:{attempt}"
        ),
    )
    session.add(job)
    document.status = "queued"
    document.processing_stage = "queued" if attempt == 1 else "retrying"
    document.error_message = None
    await session.flush()
    return job


async def claim_next_job(session: AsyncSession, *, worker_id: str) -> DocumentProcessingJob | None:
    statement = (
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.status.in_(("queued", "retrying")),
            DocumentProcessingJob.available_at <= datetime.now(UTC),
        )
        .order_by(DocumentProcessingJob.available_at, DocumentProcessingJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = await session.scalar(statement)
    if job is None:
        return None
    document = await session.get(Document, job.document_id)
    if (
        document is None
        or document.deleted_at is not None
        or document.status in {"deleting", "deleted"}
    ):
        job.status = "cancelled"
        job.retryable = False
        job.completed_at = datetime.now(UTC)
        await session.commit()
        return None
    job.status = "processing"
    job.locked_by = worker_id
    job.started_at = job.started_at or datetime.now(UTC)
    job.heartbeat_at = datetime.now(UTC)
    document.status = "processing"
    document.processing_stage = "processing"
    await session.commit()
    return job


async def schedule_retry_or_exhaust(
    session: AsyncSession,
    *,
    job: DocumentProcessingJob,
    document: Document,
    settings: Settings,
    category: str,
) -> None:
    now = datetime.now(UTC)
    if job.attempt <= settings.processing_retry_limit and job.retryable:
        job.status = "retryable_failure"
        job.completed_at = now
        document.status = "retryable_failure"
        document.processing_stage = "failed"
        delay = settings.processing_retry_base_seconds * (2 ** max(0, job.attempt - 1))
        retry = DocumentProcessingJob(
            user_id=job.user_id,
            workspace_id=job.workspace_id,
            document_id=job.document_id,
            attempt=job.attempt + 1,
            status="retrying",
            available_at=now + timedelta(seconds=delay),
            idempotency_key=(
                f"document:{job.document_id}:version:{document.current_version}:attempt:"
                f"{job.attempt + 1}"
            ),
            safe_error_category=category,
        )
        session.add(retry)
    else:
        job.status = "permanent_failure"
        job.retryable = False
        job.completed_at = now
        document.status = "permanent_failure"
        document.processing_stage = "failed"
    document.safe_error_category = category
    document.retry_count = job.attempt
    await session.commit()


class DocumentWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
        self.processor = DocumentProcessor(
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )

    async def run_once(self) -> bool:
        async with self.sessions() as session:
            await self._heartbeat(session, "ready")
            await session.commit()
            job = await claim_next_job(session, worker_id=self.worker_id)
            if job is None:
                return False
            job_id = job.id
            document_id = job.document_id
        try:
            await self.processor.process(self.sessions, document_id, force=True)
        except DocumentProcessingError as exc:
            async with self.sessions() as session:
                job = await session.get(DocumentProcessingJob, job_id)
                document = await session.get(Document, document_id)
                if job is not None and document is not None:
                    await schedule_retry_or_exhaust(
                        session,
                        job=job,
                        document=document,
                        settings=self.settings,
                        category=exc.code,
                    )
            return True
        async with self.sessions() as session:
            await self._heartbeat(session, "ready")
            await session.commit()
        return True

    async def run_forever(self) -> None:
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(self.settings.worker_poll_interval_seconds)

    async def _heartbeat(self, session: AsyncSession, status: str) -> None:
        heartbeat = await session.get(WorkerHeartbeat, self.worker_id)
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(
                worker_id=self.worker_id,
                status=status,
                last_seen_at=datetime.now(UTC),
                metadata_payload={"provider": "database"},
            )
            session.add(heartbeat)
        else:
            heartbeat.status = status
            heartbeat.last_seen_at = datetime.now(UTC)
        await session.flush()


def build_job_provider(settings: Settings) -> JobProvider:
    if settings.job_provider == "inline":
        return InlineJobProvider(settings)
    return DatabaseJobProvider(settings)


__all__ = [
    "ACTIVE_JOB_STATUSES",
    "DatabaseJobProvider",
    "DocumentWorker",
    "InlineJobProvider",
    "JobProvider",
    "JobQueueError",
    "build_job_provider",
    "claim_next_job",
    "enqueue_document_job",
    "schedule_retry_or_exhaust",
]
