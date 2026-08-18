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
    DocumentVersion,
    WorkerHeartbeat,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.documents import (
    DocumentProcessingError,
    DocumentProcessor,
    build_document_storage,
    build_embedding_provider,
    build_versioned_object_storage,
)
from opencanvas_api.services.durable_jobs import (
    DurableJobConflictError,
    DurableJobMetrics,
    DurableJobService,
    JobLease,
    RetryClassification,
)
from opencanvas_api.services.object_ingestion import ObjectReconciler
from opencanvas_api.services.observability import OperationalTelemetry, Severity
from opencanvas_api.services.scanner_bridge import build_private_scanner_result_bridge

ACTIVE_JOB_STATUSES = (
    "queued",
    "retrying",
    "retry_waiting",
    "claimed",
    "processing",
    "extracting",
    "chunking",
    "embedding",
    "indexing",
)


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
        if document.deleted_at is not None or document.status in {"deleting", "deleted"}:
            raise JobQueueError("A deleted document cannot be queued.")
        active = await session.scalar(
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.document_id == document.id,
                DocumentProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                DocumentProcessingJob.completed_at.is_(None),
            )
            .order_by(DocumentProcessingJob.created_at.desc())
            .limit(1)
        )
        if active is not None and not force:
            return active
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version == document.current_version,
                DocumentVersion.deleted_at.is_(None),
            )
        )
        if version is None:
            raise JobQueueError("The current document version is unavailable.")
        run_ordinal = (
            await session.scalar(
                select(func.count(DocumentProcessingJob.id)).where(
                    DocumentProcessingJob.document_id == document.id
                )
            )
            or 0
        ) + 1
        principal = Principal(
            user_id=user_id,
            email="",
            display_name="",
            session_id=None,
            csrf_token_hash=None,
        )
        service = _durable_service(session, self.settings)
        return await service.create_document_job(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=document.canvas_id,
            document_id=document.id,
            document_version_id=version.id,
            idempotency_key=(
                f"document:{document.id}:version:{document.current_version}:run:{run_ordinal}"
            ),
            deadline_at=datetime.now(UTC)
            + timedelta(seconds=self.settings.processing_job_deadline_seconds),
            max_attempts=self.settings.processing_retry_limit + 1,
        )


@dataclass(frozen=True, slots=True)
class InlineJobProvider(DatabaseJobProvider):
    name: str = "inline"
    runs_inline: bool = True

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
        telemetry: OperationalTelemetry | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
        self.metrics = DurableJobMetrics()
        self.telemetry = telemetry
        self.scanner_bridge = build_private_scanner_result_bridge(settings)
        self.object_storage = (
            build_versioned_object_storage(settings)
            if settings.object_ingestion_mode != "disabled"
            else None
        )
        self.processor = DocumentProcessor(
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )

    async def run_once(self) -> bool:
        async with self.sessions() as session:
            await self._heartbeat(session, "ready")
            if self.object_storage is not None:
                deleted = await ObjectReconciler(
                    session,
                    settings=self.settings,
                ).execute_deletion_requests(self.object_storage)
                if deleted:
                    await session.commit()
                    return True
            if self.scanner_bridge is not None and await self.scanner_bridge.consume_once(session):
                await session.commit()
                return True
            service = _durable_service(session, self.settings, metrics=self.metrics)
            await service.refresh_backlog_metrics()
            self._observe_metrics()
            await service.reconcile_deadlines()
            await service.recover_expired()
            lease = await service.claim_one(worker_id=self.worker_id)
            await session.commit()
            if lease is None:
                return False
            job = await session.get(DocumentProcessingJob, lease.job_run_id)
            if job is None:
                raise JobQueueError("The claimed durable job is unavailable.")
            document_id = job.document_id
            workspace_id = job.workspace_id
        span = (
            self.telemetry.start_span(
                "worker.execution",
                component="worker",
                links=(
                    self.telemetry.span_link(
                        "durable_job",
                        lease.job_run_id,
                        scope=(workspace_id, self.settings.runtime_mode.value),
                    ),
                ),
                attributes={
                    "operation": "document_processing",
                    "component": "worker",
                    "correlation": self.telemetry.correlate(
                        "worker",
                        self.worker_id,
                        scope=(self.settings.runtime_mode.value,),
                    ),
                    "linked_correlation": self.telemetry.correlate(
                        "durable_job",
                        lease.job_run_id,
                        scope=(workspace_id, self.settings.runtime_mode.value),
                    ),
                },
            )
            if self.telemetry is not None
            else None
        )
        lease_lost = asyncio.Event()
        stop_renewal = asyncio.Event()
        renewal = asyncio.create_task(self._renew_lease(lease, stop=stop_renewal, lost=lease_lost))
        try:
            async with self.sessions() as session:
                await self.processor.process_with_session(
                    session,
                    document_id,
                    force=True,
                    manage_job=False,
                )
                stop_renewal.set()
                await renewal
                if lease_lost.is_set():
                    raise DurableJobConflictError("The worker lost its durable lease.")
                job = await session.get(DocumentProcessingJob, lease.job_run_id)
                if job is None:
                    raise DurableJobConflictError("The durable job disappeared.")
                await _durable_service(
                    session,
                    self.settings,
                    metrics=self.metrics,
                ).complete(lease)
                await self._heartbeat(session, "ready")
                await session.commit()
            if span is not None:
                span.end(outcome="success")
        except DocumentProcessingError as exc:
            stop_renewal.set()
            if not renewal.done():
                await renewal
            async with self.sessions() as session:
                try:
                    await _durable_service(
                        session,
                        self.settings,
                        metrics=self.metrics,
                    ).fail(
                        lease,
                        classification=_retry_classification(exc.code),
                    )
                    await session.commit()
                except DurableJobConflictError:
                    await session.rollback()
            if span is not None:
                span.end(
                    outcome="server_error",
                    failure_class=_retry_classification(exc.code).value,
                )
            return True
        except DurableJobConflictError:
            if span is not None:
                span.end(outcome="denied", failure_class="stale_worker_suppressed")
            return True
        finally:
            stop_renewal.set()
            if not renewal.done():
                await renewal
        return True

    async def run_forever(self) -> None:
        try:
            while True:
                processed = await self.run_once()
                if not processed:
                    await asyncio.sleep(self.settings.worker_poll_interval_seconds)
        except asyncio.CancelledError:
            async with self.sessions() as session:
                await self._heartbeat(session, "stopping")
                await session.commit()
            raise

    async def _renew_lease(
        self,
        lease: JobLease,
        *,
        stop: asyncio.Event,
        lost: asyncio.Event,
    ) -> None:
        interval = min(
            self.settings.worker_heartbeat_seconds,
            max(1, self.settings.processing_lease_seconds // 3),
        )
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                async with self.sessions() as session:
                    await _durable_service(
                        session,
                        self.settings,
                        metrics=self.metrics,
                    ).renew(lease)
                    await self._heartbeat(session, "processing")
                    await session.commit()
            except Exception:
                lost.set()
                return

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

    def _observe_metrics(self) -> None:
        if self.telemetry is None:
            return
        labels = {"component": "queue", "outcome": "success"}
        self.telemetry.record_metric(
            "mobius.queue.depth",
            self.metrics.queue_depth,
            labels=labels,
        )
        self.telemetry.record_metric(
            "mobius.queue.oldest_age",
            self.metrics.oldest_queue_age_seconds,
            labels=labels,
        )
        self.telemetry.emit_log(
            event_name="worker.state.changed",
            severity=Severity.INFO,
            component="worker",
            fields={
                "operation": "worker_poll",
                "state": "healthy",
                "outcome": "success",
                "correlation_kind": "worker",
                "correlation": self.telemetry.correlate(
                    "worker",
                    self.worker_id,
                    scope=(self.settings.runtime_mode.value,),
                ),
            },
        )
        self.telemetry.schedule_flush()


def build_job_provider(settings: Settings) -> JobProvider:
    if settings.job_provider == "inline":
        return InlineJobProvider(settings)
    return DatabaseJobProvider(settings)


def _durable_service(
    session: AsyncSession,
    settings: Settings,
    *,
    metrics: DurableJobMetrics | None = None,
) -> DurableJobService:
    return DurableJobService(
        session,
        lease_seconds=settings.processing_lease_seconds,
        max_workspace_concurrency=settings.processing_max_concurrent_per_workspace,
        max_global_concurrency=settings.processing_max_concurrent_global,
        retry_base_seconds=settings.processing_retry_base_seconds,
        retry_max_seconds=settings.processing_retry_max_seconds,
        metrics=metrics,
    )


def _retry_classification(code: str) -> RetryClassification:
    mapping = {
        "storage_unavailable": RetryClassification.DEPENDENCY_UNAVAILABLE,
        "embedding_failed": RetryClassification.DEPENDENCY_UNAVAILABLE,
        "provider_timeout": RetryClassification.PROVIDER_TIMEOUT,
        "source_not_clean": RetryClassification.POLICY_REJECTED,
        "clean_source_changed": RetryClassification.SOURCE_SUPERSEDED,
        "unsupported_format": RetryClassification.UNSUPPORTED_FORMAT,
    }
    return mapping.get(code, RetryClassification.UNKNOWN_FAILURE)


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
