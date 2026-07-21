from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Canvas,
    Document,
    DocumentProcessingJob,
    WorkerHeartbeat,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.jobs import (
    JobQueueError,
    claim_next_job,
    enqueue_document_job,
    schedule_retry_or_exhaust,
)


async def _create_documents(database: Database, count: int) -> list[uuid.UUID]:
    async with database.sessions() as session:
        canvas = Canvas(workspace_id=SYSTEM_WORKSPACE_ID, name="Job reliability")
        session.add(canvas)
        await session.flush()
        documents = [
            Document(
                canvas_id=canvas.id,
                file_name=f"job-{index}.txt",
                file_type="txt",
                media_type="text/plain",
                file_size_bytes=32,
                content_sha256=f"{index:064x}",
                status="uploaded",
                processing_stage="uploading",
            )
            for index in range(count)
        ]
        session.add_all(documents)
        await session.commit()
        return [document.id for document in documents]


@pytest.mark.security
async def test_job_enqueue_is_idempotent_and_enforces_workspace_concurrency(
    app: FastAPI,
    database: Database,
) -> None:
    current = cast(Settings, app.dependency_overrides[get_settings]())
    settings = current.model_copy(update={"processing_max_concurrent_per_workspace": 1})
    first_id, second_id = await _create_documents(database, 2)
    async with database.sessions() as session:
        first = await session.get(Document, first_id)
        second = await session.get(Document, second_id)
        assert first is not None and second is not None
        first_job = await enqueue_document_job(
            session,
            settings=settings,
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            document=first,
            force=False,
        )
        duplicate = await enqueue_document_job(
            session,
            settings=settings,
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            document=first,
            force=False,
        )
        assert duplicate.id == first_job.id
        with pytest.raises(JobQueueError, match="concurrent processing-job limit"):
            await enqueue_document_job(
                session,
                settings=settings,
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                document=second,
                force=False,
            )
        await session.commit()
    async with database.sessions() as session:
        jobs = list((await session.scalars(select(DocumentProcessingJob))).all())
    assert len(jobs) == 1
    assert jobs[0].attempt == 1
    assert jobs[0].idempotency_key == f"document:{first_id}:version:1:attempt:1"


@pytest.mark.security
async def test_retry_backoff_exhaustion_and_deleted_document_cancellation(
    app: FastAPI,
    database: Database,
) -> None:
    current = cast(Settings, app.dependency_overrides[get_settings]())
    settings = current.model_copy(
        update={"processing_retry_limit": 1, "processing_retry_base_seconds": 7}
    )
    retry_document_id, deleted_document_id = await _create_documents(database, 2)
    async with database.sessions() as session:
        document = await session.get(Document, retry_document_id)
        assert document is not None
        first_job = await enqueue_document_job(
            session,
            settings=settings,
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            document=document,
            force=False,
        )
        first_job.status = "processing"
        before_retry = datetime.now(UTC)
        await schedule_retry_or_exhaust(
            session,
            job=first_job,
            document=document,
            settings=settings,
            category="storage_unavailable",
        )
    async with database.sessions() as session:
        retry_jobs = list(
            (
                await session.scalars(
                    select(DocumentProcessingJob)
                    .where(DocumentProcessingJob.document_id == retry_document_id)
                    .order_by(DocumentProcessingJob.attempt)
                )
            ).all()
        )
        document = await session.get(Document, retry_document_id)
        assert len(retry_jobs) == 2
        assert retry_jobs[0].status == "retryable_failure"
        assert retry_jobs[1].status == "retrying"
        available_at = retry_jobs[1].available_at
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=UTC)
        assert available_at >= before_retry + timedelta(seconds=7)
        assert document is not None
        retry_jobs[1].status = "processing"
        await schedule_retry_or_exhaust(
            session,
            job=retry_jobs[1],
            document=document,
            settings=settings,
            category="storage_unavailable",
        )
    async with database.sessions() as session:
        exhausted = await session.get(Document, retry_document_id)
        jobs = list(
            (
                await session.scalars(
                    select(DocumentProcessingJob).where(
                        DocumentProcessingJob.document_id == retry_document_id
                    )
                )
            ).all()
        )
        assert exhausted is not None
        assert exhausted.status == "permanent_failure"
        assert exhausted.retry_count == 2
        assert [job.status for job in jobs] == ["retryable_failure", "permanent_failure"]

        deleted = await session.get(Document, deleted_document_id)
        assert deleted is not None
        delayed = await enqueue_document_job(
            session,
            settings=settings.model_copy(update={"processing_max_concurrent_per_workspace": 3}),
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            document=deleted,
            force=False,
        )
        deleted.status = "deleted"
        deleted.processing_stage = "deleted"
        deleted.deleted_at = datetime.now(UTC)
        await session.commit()
        claimed = await claim_next_job(session, worker_id="test-worker")
        assert claimed is None
        await session.refresh(delayed)
        assert delayed.status == "cancelled"
        assert delayed.retryable is False


@pytest.mark.security
async def test_worker_health_requires_a_fresh_database_heartbeat(
    app: FastAPI,
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
) -> None:
    current = cast(Settings, app.dependency_overrides[get_settings]())
    settings = current.model_copy(
        update={"job_provider": "database", "worker_stale_after_seconds": 30}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    unavailable = await client.get(f"{api_prefix}/health/worker")
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "worker_unavailable"

    async with database.sessions() as session:
        session.add(
            WorkerHeartbeat(
                worker_id="test-worker",
                status="ready",
                last_seen_at=datetime.now(UTC),
                metadata_payload={"provider": "database"},
            )
        )
        await session.commit()
    ready = await client.get(f"{api_prefix}/health/worker")
    assert ready.status_code == 200
    assert ready.json()["service"] == "opencanvas-worker"

    async with database.sessions() as session:
        heartbeat = await session.get(WorkerHeartbeat, "test-worker")
        assert heartbeat is not None
        heartbeat.last_seen_at = datetime.now(UTC) - timedelta(seconds=31)
        await session.commit()
    stale = await client.get(f"{api_prefix}/health/ready")
    assert stale.status_code == 503
    assert stale.json()["code"] == "worker_unavailable"
