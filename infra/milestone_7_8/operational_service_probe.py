"""Bounded production-service observations for an isolated synthetic fixture.

No synthetic metrics, test clocks, invented failures, or provider operations.
The caller admits the stopped worker, runtime, source and execution authority.
"""

from __future__ import annotations

import asyncio
import uuid
import time
from datetime import UTC, datetime, timedelta
from typing import Any


async def queue_transitions(
    db: Any, settings: Any, fixture: dict, journal: Any
) -> dict:
    from infra.milestone_7_8.pilot_application_probe import require

    bound = settings.processing_lease_seconds + 120
    require(
        bound <= 600
        and datetime.now(UTC) + timedelta(seconds=bound) < journal.deadline,
        "existing lease plus recovery margin exceeds bounded remaining window",
    )
    started = time.perf_counter()
    async with asyncio.timeout(bound):
        result = await _queue_transitions(db, settings, fixture, journal)
    result["elapsedSeconds"] = time.perf_counter() - started
    result["maximumElapsedSeconds"] = bound
    return result


async def _queue_transitions(
    db: Any, settings: Any, fixture: dict, journal: Any
) -> dict:
    from sqlalchemy import select

    from opencanvas_api.db.models import (
        Document,
        DocumentProcessingJob,
        DocumentVersion,
        DurableJobDeadLetter,
        DurableJobOutcome,
    )
    from opencanvas_api.services.auth import Principal
    from opencanvas_api.services.durable_jobs import DurableJobConflictError
    from opencanvas_api.services.jobs import ACTIVE_JOB_STATUSES, _durable_service

    from infra.milestone_7_8.pilot_application_probe import require

    workspace = uuid.UUID(fixture["workspaceId"])
    document_id = uuid.UUID(fixture["queued"]["documentId"])
    principal = Principal(
        user_id=uuid.UUID(fixture["userId"]),
        email="scoped-observation@mobius.invalid",
        display_name="Recorded synthetic fixture actor",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )

    async def active(session: Any) -> list:
        return list(
            (
                await session.scalars(
                    select(DocumentProcessingJob.id).where(
                        DocumentProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                        DocumentProcessingJob.completed_at.is_(None),
                    )
                )
            ).all()
        )

    async with db.sessions() as session:
        require(not await active(session), "isolated queue must be drained")
        document = await session.get(Document, document_id)
        require(
            document is not None
            and document.status == "ready"
            and str(document.canvas_id) == fixture["canvasId"],
            "exact ready synthetic document required",
        )
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version == document.current_version,
            )
        )
        require(version is not None, "current synthetic source version absent")
        service = _durable_service(session, settings)
        job = await service.create_document_job(
            principal=principal,
            workspace_id=workspace,
            canvas_id=uuid.UUID(fixture["canvasId"]),
            document_id=document_id,
            document_version_id=version.id,
            idempotency_key=journal.header["executionId"] + ":observed-expiry",
            deadline_at=journal.deadline,
            max_attempts=1,
        )
        job_id = job.id
        lease = await service.claim_one(worker_id="bounded-operational-observer")
        require(
            lease is not None and lease.job_run_id == job_id,
            "only exact synthetic job may be claimed",
        )
        await session.commit()
    journal.step(
        "observed-lease-created",
        {"jobId": str(job_id), "expiresAt": lease.expires_at.isoformat()},
    )
    while datetime.now(UTC) <= lease.expires_at:
        journal.check_time()
        await asyncio.sleep(
            min(1, max(0.01, (lease.expires_at - datetime.now(UTC)).total_seconds()))
        )
    async with db.sessions() as session:
        require(
            await active(session) == [job_id], "queue isolation changed before recovery"
        )
        service = _durable_service(session, settings)
        try:
            await service.complete(lease)
        except DurableJobConflictError:
            await session.rollback()
        else:
            await session.rollback()
            raise ValueError("expired actual lease was accepted")
    async with db.sessions() as session:
        require(
            await active(session) == [job_id], "queue isolation changed before recovery"
        )
        require(
            await _durable_service(session, settings).recover_expired(limit=1) == 1,
            "actual expired lease did not recover",
        )
        await session.commit()
    journal.step(
        "observed-dead-letter", {"jobId": str(job_id), "cause": "actual-lease-expiry"}
    )
    async with db.sessions() as session:
        dead = await session.scalar(
            select(DurableJobDeadLetter).where(
                DurableJobDeadLetter.job_run_id == job_id
            )
        )
        require(dead is not None, "durable dead-letter record absent")
        replay = await _durable_service(session, settings).replay(
            principal=principal,
            workspace_id=workspace,
            dead_letter_id=dead.dead_letter_id,
            reason_code="operator_retry",
            idempotency_key=journal.header["executionId"] + ":observed-replay",
        )
        replay_id = replay.id
        require(replay_id != job_id, "replay must receive a new identity")
        await session.commit()
    journal.step(
        "observed-replay", {"sourceJobId": str(job_id), "replayJobId": str(replay_id)}
    )
    async with db.sessions() as session:
        require(
            await active(session) == [replay_id], "unexpected active job after replay"
        )
        await _durable_service(session, settings).cancel(
            principal=principal,
            workspace_id=workspace,
            job_run_id=replay_id,
            reason_code="operational_proof_complete",
        )
        await session.commit()
    async with db.sessions() as session:
        require(not await active(session), "operational fixture left active work")
        outcomes = list(
            (
                await session.scalars(
                    select(DurableJobOutcome).where(
                        DurableJobOutcome.job_run_id.in_((job_id, replay_id))
                    )
                )
            ).all()
        )
        require(
            len(outcomes) == 2
            and {row.job_run_id for row in outcomes} == {job_id, replay_id},
            "exactly one terminal effect per fixture job required",
        )
    return {
        "jobId": str(job_id),
        "replayJobId": str(replay_id),
        "actualLeaseExpired": True,
        "deadLettered": True,
        "replayed": True,
        "replayCanceled": True,
        "activeFixtureJobs": 0,
        "managedAcceptance": "service observations only; destination evidence still required",
    }
