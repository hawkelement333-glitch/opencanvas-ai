from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Canvas,
    Document,
    DocumentProcessingJob,
    DocumentVersion,
    DomainEventRecord,
    DurableJobAuditEvent,
    DurableJobDeadLetter,
    DurableJobOutcome,
    DurableJobReplayRequest,
    DurableJobRequest,
    DurableQueueDelivery,
    DurableRetryDecision,
    TraceEvent,
    WorkspaceAuthorityVersion,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.durable_jobs import (
    DurableJobConflictError,
    DurableJobService,
    RetryClassification,
)
from opencanvas_api.services.trace import TraceService


async def _source(database: Database) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with database.sessions() as session:
        canvas = Canvas(workspace_id=SYSTEM_WORKSPACE_ID, name="Durable jobs")
        session.add(canvas)
        await session.flush()
        document = Document(
            canvas_id=canvas.id,
            file_name="durable.txt",
            file_type="txt",
            media_type="text/plain",
            file_size_bytes=7,
            content_sha256="a" * 64,
            status="uploaded",
            processing_stage="uploading",
        )
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version=1,
            file_name=document.file_name,
            file_type=document.file_type,
            media_type=document.media_type,
            file_size_bytes=document.file_size_bytes,
            content_sha256=document.content_sha256,
            storage_key=f"test/{document.id}/1",
            status="uploaded",
        )
        session.add(version)
        await session.commit()
        return canvas.id, document.id, version.id


def _principal() -> Principal:
    return Principal(
        user_id=SYSTEM_USER_ID,
        email="test-system@mobius.invalid",
        display_name="Test system user",
        session_id=None,
        csrf_token_hash=None,
    )


async def _create(
    database: Database,
    *,
    now: datetime,
    idempotency_key: str = "durable-test-1",
    max_attempts: int = 3,
) -> uuid.UUID:
    canvas_id, document_id, version_id = await _source(database)
    async with database.sessions() as session:
        job = await DurableJobService(
            session,
            lease_seconds=10,
            retry_base_seconds=1,
            retry_max_seconds=8,
        ).create_document_job(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version_id=version_id,
            idempotency_key=idempotency_key,
            deadline_at=now + timedelta(minutes=10),
            max_attempts=max_attempts,
            now=now,
        )
        await session.commit()
        return job.id


@pytest.mark.security
async def test_exact_duplicate_request_and_completion_execute_once(database: Database) -> None:
    now = datetime.now(UTC)
    canvas_id, document_id, version_id = await _source(database)
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        first = await service.create_document_job(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version_id=version_id,
            idempotency_key="duplicate-request",
            deadline_at=now + timedelta(minutes=5),
            now=now,
        )
        duplicate = await service.create_document_job(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version_id=version_id,
            idempotency_key="duplicate-request",
            deadline_at=now + timedelta(minutes=5),
            now=now,
        )
        assert duplicate.id == first.id
        await session.commit()

    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        lease = await service.claim_one(worker_id="worker-a", now=now + timedelta(seconds=1))
        assert lease is not None
        result_id = uuid.uuid4()
        outcome = await service.complete(
            lease,
            result_id=result_id,
            now=now + timedelta(seconds=2),
        )
        duplicate_outcome = await service.complete(
            lease,
            result_id=result_id,
            now=now + timedelta(seconds=2),
        )
        assert duplicate_outcome.outcome_id == outcome.outcome_id
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(DurableJobRequest.request_id))) == 1
        assert await session.scalar(select(func.count(DocumentProcessingJob.id))) == 1
        assert await session.scalar(select(func.count(DurableQueueDelivery.delivery_id))) == 1
        assert await session.scalar(select(func.count(DurableJobOutcome.outcome_id))) == 1
        assert await session.scalar(select(func.count(DurableJobAuditEvent.audit_event_id))) == 3
        assert (
            await session.scalar(
                select(func.count(DomainEventRecord.event_id)).where(
                    DomainEventRecord.subject_kind == "durable_job"
                )
            )
            == 3
        )
        assert (
            await session.scalar(
                select(func.count(TraceEvent.event_id)).where(
                    TraceEvent.object_type == "durable_job"
                )
            )
            == 3
        )


@pytest.mark.security
async def test_bounded_retry_succeeds_once_and_stale_worker_is_fenced(
    database: Database,
) -> None:
    now = datetime.now(UTC)
    job_id = await _create(database, now=now)
    async with database.sessions() as session:
        service = DurableJobService(
            session,
            lease_seconds=5,
            retry_base_seconds=1,
            retry_max_seconds=1,
        )
        first = await service.claim_one(worker_id="worker-stale", now=now)
        assert first is not None
        await session.commit()

    async with database.sessions() as session:
        service = DurableJobService(
            session,
            lease_seconds=5,
            retry_base_seconds=1,
            retry_max_seconds=1,
        )
        assert await service.recover_expired(now=now + timedelta(seconds=6)) == 1
        replacement = await service.claim_one(
            worker_id="worker-recovered",
            now=now + timedelta(seconds=7),
        )
        assert replacement is not None
        with pytest.raises(DurableJobConflictError):
            await service.complete(first, now=now + timedelta(seconds=7))
        outcome = await service.complete(
            replacement,
            result_id=uuid.uuid4(),
            now=now + timedelta(seconds=8),
        )
        assert outcome.outcome == "succeeded"
        await session.commit()

    async with database.sessions() as session:
        job = await session.get(DocumentProcessingJob, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.attempt_count == 2
        assert await session.scalar(select(func.count(DurableJobOutcome.outcome_id))) == 1


@pytest.mark.security
async def test_transient_retry_is_bounded_and_succeeds_once(database: Database) -> None:
    now = datetime.now(UTC)
    job_id = await _create(database, now=now, idempotency_key="transient")
    async with database.sessions() as session:
        service = DurableJobService(
            session,
            lease_seconds=10,
            retry_base_seconds=1,
            retry_max_seconds=1,
        )
        first = await service.claim_one(worker_id="worker-first", now=now)
        assert first is not None
        decision = await service.fail(
            first,
            classification=RetryClassification.DEPENDENCY_UNAVAILABLE,
            now=now + timedelta(seconds=1),
        )
        assert decision.disposition == "retry"
        assert 0 <= decision.delay_ms <= 1_000
        await session.commit()
    async with database.sessions() as session:
        service = DurableJobService(
            session,
            lease_seconds=10,
            retry_base_seconds=1,
            retry_max_seconds=1,
        )
        second = await service.claim_one(
            worker_id="worker-second",
            now=now + timedelta(seconds=3),
        )
        assert second is not None
        assert second.job_run_id == job_id
        assert second.attempt_number == 2
        first_outcome = await service.complete(
            second,
            result_id=uuid.uuid4(),
            now=now + timedelta(seconds=4),
        )
        duplicate = await service.complete(
            second,
            result_id=first_outcome.result_id,
            now=now + timedelta(seconds=4),
        )
        assert duplicate.outcome_id == first_outcome.outcome_id
        await session.commit()


@pytest.mark.security
async def test_claiming_respects_bounded_priority_and_reports_backlog(
    database: Database,
) -> None:
    now = datetime.now(UTC)
    low_canvas, low_document, low_version = await _source(database)
    high_canvas, high_document, high_version = await _source(database)
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        low = await service.create_document_job(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=low_canvas,
            document_id=low_document,
            document_version_id=low_version,
            idempotency_key="priority-low",
            deadline_at=now + timedelta(minutes=5),
            priority=10,
            now=now,
        )
        high = await service.create_document_job(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=high_canvas,
            document_id=high_document,
            document_version_id=high_version,
            idempotency_key="priority-high",
            deadline_at=now + timedelta(minutes=5),
            priority=90,
            now=now,
        )
        await service.refresh_backlog_metrics(now=now + timedelta(seconds=1))
        assert service.metrics.queue_depth == 2
        assert service.metrics.oldest_queue_age_seconds >= 0
        lease = await service.claim_one(
            worker_id="priority-worker",
            now=now + timedelta(seconds=1),
        )
        assert lease is not None
        assert lease.job_run_id == high.id
        assert lease.job_run_id != low.id
        await session.commit()


@pytest.mark.security
async def test_expired_final_attempt_dead_letters_without_unbounded_retry(
    database: Database,
) -> None:
    now = datetime.now(UTC)
    job_id = await _create(
        database,
        now=now,
        idempotency_key="expired-final-attempt",
        max_attempts=1,
    )
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=5)
        lease = await service.claim_one(worker_id="expiring-worker", now=now)
        assert lease is not None
        assert await service.recover_expired(now=now + timedelta(seconds=6)) == 1
        await session.commit()
    async with database.sessions() as session:
        job = await session.get(DocumentProcessingJob, job_id)
        assert job is not None
        assert job.status == "dead_lettered"
        assert job.attempt_count == 1
        assert (
            await session.scalar(
                select(func.count(DurableRetryDecision.retry_decision_id)).where(
                    DurableRetryDecision.job_run_id == job_id,
                    DurableRetryDecision.disposition == "dead_letter",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(DurableJobDeadLetter.dead_letter_id)).where(
                    DurableJobDeadLetter.job_run_id == job_id
                )
            )
            == 1
        )


@pytest.mark.security
async def test_canceled_deadline_and_revoked_jobs_cannot_commit(database: Database) -> None:
    now = datetime.now(UTC)
    canceled_id = await _create(database, now=now, idempotency_key="cancel")
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        canceled_lease = await service.claim_one(worker_id="worker-cancel", now=now)
        assert canceled_lease is not None
        await service.cancel(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            job_run_id=canceled_id,
            reason_code="user_requested",
            now=now + timedelta(seconds=1),
        )
        with pytest.raises(DurableJobConflictError):
            await service.complete(canceled_lease, now=now + timedelta(seconds=2))
        await session.commit()

    deadline_now = now + timedelta(hours=1)
    deadline_id = await _create(database, now=deadline_now, idempotency_key="deadline")
    async with database.sessions() as session:
        job = await session.get(DocumentProcessingJob, deadline_id)
        assert job is not None
        job.deadline_at = deadline_now + timedelta(seconds=2)
        await session.commit()
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        deadline_lease = await service.claim_one(worker_id="worker-deadline", now=deadline_now)
        assert deadline_lease is not None
        with pytest.raises(DurableJobConflictError):
            await service.complete(
                deadline_lease,
                now=deadline_now + timedelta(seconds=3),
            )
        await session.rollback()
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        assert await service.reconcile_deadlines(now=deadline_now + timedelta(seconds=3)) == 1
        await session.commit()

    revoked_now = now + timedelta(hours=2)
    revoked_id = await _create(database, now=revoked_now, idempotency_key="revoked")
    async with database.sessions() as session:
        authority = await session.get(WorkspaceAuthorityVersion, SYSTEM_WORKSPACE_ID)
        assert authority is not None
        authority.authority_generation += 1
        await session.commit()
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        assert await service.claim_one(worker_id="worker-revoked", now=revoked_now) is None
        await session.commit()
    async with database.sessions() as session:
        revoked = await session.get(DocumentProcessingJob, revoked_id)
        assert revoked is not None
        assert revoked.status == "permanent_failure"
        assert revoked.safe_error_category == "authority_revoked"

    superseded_now = now + timedelta(hours=3)
    superseded_id = await _create(
        database,
        now=superseded_now,
        idempotency_key="source-superseded",
    )
    async with database.sessions() as session:
        job = await session.get(DocumentProcessingJob, superseded_id)
        assert job is not None
        document = await session.get(Document, job.document_id)
        assert document is not None
        document.current_version += 1
        await session.commit()
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        assert (
            await service.claim_one(
                worker_id="worker-superseded",
                now=superseded_now,
            )
            is None
        )
        await session.commit()
    async with database.sessions() as session:
        superseded = await session.get(DocumentProcessingJob, superseded_id)
        assert superseded is not None
        assert superseded.status == "permanent_failure"
        assert superseded.safe_error_category == "source_superseded"


@pytest.mark.security
async def test_failed_transaction_leaves_no_partial_job_evidence(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    canvas_id, document_id, version_id = await _source(database)

    async def fail_trace(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("injected trace failure")

    monkeypatch.setattr(TraceService, "record_event", fail_trace)
    async with database.sessions() as session:
        with pytest.raises(RuntimeError, match="injected trace failure"):
            await DurableJobService(session, lease_seconds=10).create_document_job(
                principal=_principal(),
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                document_id=document_id,
                document_version_id=version_id,
                idempotency_key="atomic-failure",
                deadline_at=now + timedelta(minutes=5),
                now=now,
            )
        await session.rollback()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(DurableJobRequest.request_id))) == 0
        assert await session.scalar(select(func.count(DocumentProcessingJob.id))) == 0
        assert await session.scalar(select(func.count(DurableQueueDelivery.delivery_id))) == 0
        assert await session.scalar(select(func.count(DurableJobAuditEvent.audit_event_id))) == 0
        assert (
            await session.scalar(
                select(func.count(DomainEventRecord.event_id)).where(
                    DomainEventRecord.subject_kind == "durable_job"
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count(TraceEvent.event_id)).where(
                    TraceEvent.object_type == "durable_job"
                )
            )
            == 0
        )


@pytest.mark.security
async def test_poison_job_dead_letters_once(database: Database) -> None:
    now = datetime.now(UTC)
    await _create(database, now=now, idempotency_key="poison", max_attempts=3)
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        lease = await service.claim_one(worker_id="worker-poison", now=now)
        assert lease is not None
        first = await service.fail(
            lease,
            classification=RetryClassification.CORRUPT_INPUT,
            poison=True,
            now=now + timedelta(seconds=1),
        )
        duplicate = await service.fail(
            lease,
            classification=RetryClassification.CORRUPT_INPUT,
            poison=True,
            now=now + timedelta(seconds=1),
        )
        assert duplicate.retry_decision_id == first.retry_decision_id
        await session.commit()
    async with database.sessions() as session:
        assert await session.scalar(select(func.count(DurableJobOutcome.outcome_id))) == 1


@pytest.mark.security
async def test_status_and_cancel_api_expose_only_safe_scoped_state(
    app: FastAPI,
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
) -> None:
    del app
    now = datetime.now(UTC)
    job_id = await _create(database, now=now, idempotency_key="api-status")
    response = await client.get(f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["jobRunId"] == str(job_id)
    assert "lockedBy" not in response.json()
    assert "leaseGeneration" not in response.json()

    cross_scope = await client.get(f"{api_prefix}/workspaces/{uuid.uuid4()}/jobs/{job_id}")
    assert cross_scope.status_code == 404

    canceled = await client.post(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/jobs/{job_id}/cancel",
        json={"reasonCode": "user_requested"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "cancelled"


@pytest.mark.security
async def test_operator_dead_letter_api_is_redacted_and_replays_with_new_identity(
    app: FastAPI,
    client: httpx.AsyncClient,
    database: Database,
    api_prefix: str,
) -> None:
    del app
    now = datetime.now(UTC)
    source_job_id = await _create(database, now=now, idempotency_key="api-replay-source")
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        lease = await service.claim_one(worker_id="api-dead-worker", now=now)
        assert lease is not None
        await service.fail(
            lease,
            classification=RetryClassification.CORRUPT_INPUT,
            poison=True,
            now=now + timedelta(seconds=1),
        )
        await session.commit()

    listed = await client.get(f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/jobs/dead-letters")
    assert listed.status_code == 200
    summary = listed.json()[0]
    assert summary["jobRunId"] == str(source_job_id)
    assert "traceId" not in summary
    assert "auditEventId" not in summary
    assert "workerId" not in summary

    replayed = await client.post(
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/jobs/dead-letters/"
        f"{summary['deadLetterId']}/replay",
        json={
            "reasonCode": "dependency_recovered",
            "idempotencyKey": "api-operator-replay",
        },
    )
    assert replayed.status_code == 202
    assert replayed.json()["jobRunId"] != str(source_job_id)
    assert "leaseGeneration" not in replayed.json()


@pytest.mark.security
async def test_dead_letter_replay_requires_current_authority_and_new_identity(
    database: Database,
) -> None:
    now = datetime.now(UTC)
    source_job_id = await _create(database, now=now, idempotency_key="replay-source")
    async with database.sessions() as session:
        service = DurableJobService(session, lease_seconds=10)
        lease = await service.claim_one(worker_id="worker-dead", now=now)
        assert lease is not None
        await service.fail(
            lease,
            classification=RetryClassification.CORRUPT_INPUT,
            poison=True,
            now=now + timedelta(seconds=1),
        )
        await session.commit()
    async with database.sessions() as session:
        dead_letter = await session.scalar(
            select(DurableJobDeadLetter).where(DurableJobDeadLetter.job_run_id == source_job_id)
        )
        assert dead_letter is not None
        replay = await DurableJobService(session, lease_seconds=10).replay(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            dead_letter_id=dead_letter.dead_letter_id,
            reason_code="dependency_recovered",
            idempotency_key="operator-replay-1",
            now=now + timedelta(seconds=2),
        )
        duplicate = await DurableJobService(session, lease_seconds=10).replay(
            principal=_principal(),
            workspace_id=SYSTEM_WORKSPACE_ID,
            dead_letter_id=dead_letter.dead_letter_id,
            reason_code="dependency_recovered",
            idempotency_key="operator-replay-1",
            now=now + timedelta(seconds=2),
        )
        assert replay.id != source_job_id
        assert duplicate.id == replay.id
        await session.commit()
    async with database.sessions() as session:
        assert (
            await session.scalar(select(func.count(DurableJobReplayRequest.replay_request_id))) == 1
        )
