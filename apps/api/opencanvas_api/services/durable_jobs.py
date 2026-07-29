from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, cast

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    Canvas,
    Document,
    DocumentProcessingJob,
    DocumentVersion,
    DurableJobAttempt,
    DurableJobAuditEvent,
    DurableJobDeadLetter,
    DurableJobOutcome,
    DurableJobReplayRequest,
    DurableJobRequest,
    DurableQueueDelivery,
    DurableRetryDecision,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration_authority import (
    CollaborationAuthorizationService,
    CollaborationPermission,
)
from opencanvas_api.services.domain_events import (
    CreateDomainEvent,
    DomainEventService,
    RecordedDomainEvent,
)
from opencanvas_api.services.trace import RecordTraceEventInput, TraceService

ACTIVE_STATES = frozenset(
    {
        "queued",
        "retrying",
        "retry_waiting",
        "claimed",
        "processing",
        "extracting",
        "chunking",
        "embedding",
        "indexing",
    }
)
CLAIMABLE_STATES = ("queued", "retrying", "retry_waiting")
TERMINAL_STATES = frozenset(
    {"ready", "succeeded", "permanent_failure", "failed", "cancelled", "dead_lettered"}
)


class DurableJobError(RuntimeError):
    code = "durable_job_error"
    safe_message = "The background operation could not be completed."


class DurableJobValidationError(DurableJobError):
    code = "durable_job_invalid"


class DurableJobNotFoundError(DurableJobError):
    code = "durable_job_not_found"
    safe_message = "Background operation not found."


class DurableJobConflictError(DurableJobError):
    code = "durable_job_conflict"
    safe_message = "The background operation changed before this action completed."


class DurableJobUnavailableError(DurableJobError):
    code = "durable_job_unavailable"
    safe_message = "The durable queue is temporarily unavailable."


class RetryClassification(StrEnum):
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    CONNECTION_INTERRUPTED = "connection_interrupted"
    RATE_LIMITED = "rate_limited"
    LEASE_INTERRUPTED = "lease_interrupted"
    PROVIDER_TIMEOUT = "provider_timeout"
    POLICY_REJECTED = "policy_rejected"
    MALWARE = "malware"
    CORRUPT_INPUT = "corrupt_input"
    UNSUPPORTED_FORMAT = "unsupported_format"
    CANCELED = "canceled"
    AUTHORITY_REVOKED = "authority_revoked"
    SOURCE_SUPERSEDED = "source_superseded"
    DETERMINISTIC_DRIFT = "deterministic_drift"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    UNKNOWN_FAILURE = "unknown_failure"


RETRYABLE_FAILURES = frozenset(
    {
        RetryClassification.DEPENDENCY_UNAVAILABLE,
        RetryClassification.CONNECTION_INTERRUPTED,
        RetryClassification.RATE_LIMITED,
        RetryClassification.LEASE_INTERRUPTED,
        RetryClassification.PROVIDER_TIMEOUT,
    }
)


@dataclass(frozen=True, slots=True)
class JobLease:
    job_run_id: uuid.UUID
    attempt_id: uuid.UUID
    delivery_id: uuid.UUID
    worker_id: str
    lease_generation: int
    cancellation_generation: int
    authority_generation: int
    source_version: int
    attempt_number: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class JobView:
    job_run_id: uuid.UUID
    request_id: uuid.UUID | None
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID | None
    document_id: uuid.UUID
    document_version_id: uuid.UUID | None
    status: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    deadline_at: datetime | None
    completed_at: datetime | None
    safe_error_category: str | None
    cancellation_generation: int


@dataclass(slots=True)
class DurableJobMetrics:
    claims: int = 0
    claim_conflicts: int = 0
    claim_latency_ms_total: float = 0.0
    lease_losses: int = 0
    recovered_leases: int = 0
    retries: int = 0
    cancellations: int = 0
    deadline_expirations: int = 0
    dead_letters: int = 0
    replays: int = 0
    stale_results_suppressed: int = 0
    queue_depth: int = 0
    oldest_queue_age_seconds: float = 0.0


class DurableJobService:
    """PostgreSQL-backed queue truth with server-loaded scope and fenced effects."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        lease_seconds: int = 60,
        max_workspace_concurrency: int = 3,
        max_global_concurrency: int = 32,
        retry_base_seconds: int = 5,
        retry_max_seconds: int = 900,
        metrics: DurableJobMetrics | None = None,
    ) -> None:
        if not 5 <= lease_seconds <= 900:
            raise DurableJobValidationError("Lease duration is outside the closed bound.")
        if not 1 <= max_workspace_concurrency <= 100:
            raise DurableJobValidationError("Workspace concurrency is outside the closed bound.")
        if not 1 <= max_global_concurrency <= 1_000:
            raise DurableJobValidationError("Global concurrency is outside the closed bound.")
        if not 1 <= retry_base_seconds <= retry_max_seconds <= 86_400:
            raise DurableJobValidationError("Retry timing is outside the closed bound.")
        self.session = session
        self.lease_seconds = lease_seconds
        self.max_workspace_concurrency = max_workspace_concurrency
        self.max_global_concurrency = max_global_concurrency
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.metrics = metrics or DurableJobMetrics()

    async def create_document_job(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        document_id: uuid.UUID,
        document_version_id: uuid.UUID,
        idempotency_key: str,
        deadline_at: datetime,
        max_attempts: int = 4,
        priority_class: Literal["interactive", "normal", "maintenance"] = "normal",
        priority: int = 50,
        now: datetime | None = None,
    ) -> DocumentProcessingJob:
        current = _aware(now or datetime.now(UTC))
        if not idempotency_key.strip() or len(idempotency_key) > 160:
            raise DurableJobValidationError("Idempotency key is invalid.")
        if not 1 <= max_attempts <= 10 or not 0 <= priority <= 100:
            raise DurableJobValidationError("Job bounds are invalid.")
        deadline = _aware(deadline_at)
        if deadline <= current or deadline > current + timedelta(days=7):
            raise DurableJobValidationError("Job deadline is outside the closed bound.")
        decision = await CollaborationAuthorizationService(self.session).evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.RESOURCE_EDIT,
        )
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.authority_generation is None
        ):
            raise DurableJobNotFoundError()
        document = await self.session.scalar(
            select(Document)
            .join(Canvas, Canvas.id == Document.canvas_id)
            .where(
                Document.id == document_id,
                Document.canvas_id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
            )
        )
        version = await self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == document_version_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.deleted_at.is_(None),
            )
        )
        if document is None or version is None:
            raise DurableJobNotFoundError()
        request_payload = {
            "userId": str(principal.user_id),
            "membershipId": str(decision.membership_id),
            "workspaceId": str(workspace_id),
            "canvasId": str(canvas_id),
            "documentId": str(document_id),
            "documentVersionId": str(document_version_id),
            "sourceVersion": version.version,
            "requestKind": "document_processing",
            "idempotencyKey": idempotency_key,
            "authorityGeneration": decision.authority_generation,
            "maxAttempts": max_attempts,
            "deadlineAt": deadline.isoformat(),
        }
        request_digest = _digest(request_payload)
        existing = await self.session.scalar(
            select(DurableJobRequest).where(
                DurableJobRequest.user_id == principal.user_id,
                DurableJobRequest.workspace_id == workspace_id,
                DurableJobRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise DurableJobConflictError("Idempotency identity was reused.")
            job = await self.session.scalar(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.request_id == existing.request_id
                )
            )
            if job is None:
                raise DurableJobConflictError("Existing request has no durable job run.")
            return job
        request_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius:durable-job-request:{principal.user_id}:{workspace_id}:{idempotency_key}",
        )
        job_id = uuid.uuid5(request_id, "job-run")
        trace_id = uuid.uuid5(request_id, "trace")
        run_number = (
            await self.session.scalar(
                select(func.coalesce(func.max(DocumentProcessingJob.attempt), 0)).where(
                    DocumentProcessingJob.document_id == document_id
                )
            )
            or 0
        ) + 1
        request = DurableJobRequest(
            request_id=request_id,
            user_id=principal.user_id,
            membership_id=decision.membership_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version_id=document_version_id,
            request_kind="document_processing",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            authority_generation=decision.authority_generation,
            cancellation_generation=0,
            trace_id=trace_id,
            created_at=current,
        )
        job = DocumentProcessingJob(
            id=job_id,
            request_id=request_id,
            user_id=principal.user_id,
            membership_id=decision.membership_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version_id=document_version_id,
            job_kind="document_processing",
            attempt=run_number,
            attempt_count=0,
            max_attempts=max_attempts,
            status="queued",
            idempotency_key=f"job:{job_id}",
            request_digest=request_digest,
            authority_generation=decision.authority_generation,
            cancellation_generation=0,
            source_version=version.version,
            priority_class=priority_class,
            priority=priority,
            eligibility_class="ordinary",
            available_at=current,
            deadline_at=deadline,
            retryable=True,
        )
        delivery = DurableQueueDelivery(
            delivery_id=uuid.uuid5(job_id, "delivery:1"),
            job_run_id=job_id,
            user_id=principal.user_id,
            workspace_id=workspace_id,
            delivery_sequence=1,
            delivery_kind="enqueue",
            idempotency_key=f"job:{job_id}:delivery:1",
            eligible_at=current,
            created_at=current,
        )
        self.session.add(request)
        await self.session.flush()
        self.session.add(job)
        await self.session.flush()
        self.session.add(delivery)
        await self.session.flush()
        audit = await self._record_material(
            job=job,
            action="created",
            status="queued",
            reason_code="job_accepted",
            trace_id=trace_id,
            now=current,
            actor_user_id=principal.user_id,
        )
        await self._record_domain_event(
            job=job,
            action="created",
            status="queued",
            reason_code="job_accepted",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            now=current,
        )
        document.status = "queued"
        document.processing_stage = "queued"
        return job

    async def claim_one(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> JobLease | None:
        current = _aware(now or datetime.now(UTC))
        claim_started = datetime.now(UTC)
        if not worker_id.strip() or len(worker_id) > 120:
            raise DurableJobValidationError("Worker identity is invalid.")
        global_active = await self.session.scalar(
            select(func.count(DocumentProcessingJob.id)).where(
                DocumentProcessingJob.locked_by.is_not(None),
                DocumentProcessingJob.lease_expires_at > current,
            )
        )
        if (global_active or 0) >= self.max_global_concurrency:
            return None
        eligible = and_(
            DocumentProcessingJob.status.in_(CLAIMABLE_STATES),
            DocumentProcessingJob.available_at <= current,
            DocumentProcessingJob.completed_at.is_(None),
            DocumentProcessingJob.attempt_count < DocumentProcessingJob.max_attempts,
            or_(
                DocumentProcessingJob.deadline_at.is_(None),
                DocumentProcessingJob.deadline_at > current,
            ),
            or_(
                DocumentProcessingJob.locked_by.is_(None),
                DocumentProcessingJob.lease_expires_at <= current,
            ),
        )
        statement = (
            select(DocumentProcessingJob)
            .where(eligible, DocumentProcessingJob.legacy_backfill.is_(False))
            .order_by(
                DocumentProcessingJob.available_at,
                DocumentProcessingJob.priority.desc(),
                DocumentProcessingJob.workspace_id,
                DocumentProcessingJob.created_at,
                DocumentProcessingJob.id,
            )
            .limit(16)
            .with_for_update(skip_locked=True)
        )
        try:
            candidates = list((await self.session.scalars(statement)).all())
        except OperationalError as exc:
            if self.session.get_bind().dialect.name == "sqlite" and "locked" in str(exc).lower():
                self.metrics.claim_conflicts += 1
                return None
            raise DurableJobUnavailableError() from exc
        for candidate in candidates:
            active = await self.session.scalar(
                select(func.count(DocumentProcessingJob.id)).where(
                    DocumentProcessingJob.workspace_id == candidate.workspace_id,
                    DocumentProcessingJob.locked_by.is_not(None),
                    DocumentProcessingJob.lease_expires_at > current,
                )
            )
            if (active or 0) >= self.max_workspace_concurrency:
                continue
            boundary_failure = await self._boundary_failure(candidate)
            if boundary_failure is not None:
                await self._terminalize_without_lease(
                    candidate,
                    outcome=(
                        "authority_revoked" if boundary_failure == "authority_revoked" else "failed"
                    ),
                    status="permanent_failure",
                    reason_code=boundary_failure,
                    now=current,
                )
                continue
            generation = candidate.lease_generation + 1
            attempt_number = candidate.attempt_count + 1
            expires_at = min(
                current + timedelta(seconds=self.lease_seconds),
                _aware(candidate.deadline_at)
                if candidate.deadline_at is not None
                else current + timedelta(seconds=self.lease_seconds),
            )
            delivery = await self._current_delivery(candidate.id, current)
            if delivery is None:
                raise DurableJobConflictError("Claimable job has no queue delivery.")
            claimed = await self.session.scalar(
                update(DocumentProcessingJob)
                .where(
                    DocumentProcessingJob.id == candidate.id,
                    DocumentProcessingJob.lease_generation == candidate.lease_generation,
                    DocumentProcessingJob.cancellation_generation
                    == candidate.cancellation_generation,
                    eligible,
                )
                .values(
                    status="claimed",
                    locked_by=worker_id,
                    lease_generation=generation,
                    lease_expires_at=expires_at,
                    heartbeat_at=current,
                    started_at=func.coalesce(DocumentProcessingJob.started_at, current),
                    attempt_count=attempt_number,
                )
                .returning(DocumentProcessingJob.id)
                .execution_options(synchronize_session=False)
            )
            if claimed is None:
                self.metrics.claim_conflicts += 1
                continue
            await self.session.refresh(candidate)
            attempt_id = uuid.uuid5(candidate.id, f"attempt:{attempt_number}")
            self.session.add(
                DurableJobAttempt(
                    attempt_id=attempt_id,
                    job_run_id=candidate.id,
                    delivery_id=delivery.delivery_id,
                    user_id=candidate.user_id,
                    workspace_id=candidate.workspace_id,
                    attempt_number=attempt_number,
                    lease_generation=generation,
                    worker_id=worker_id,
                    outcome="running",
                    started_at=current,
                    recorded_at=current,
                )
            )
            claim_trace_id = uuid.uuid5(candidate.id, f"claim:{generation}")
            audit = await self._record_material(
                job=candidate,
                action="claimed",
                status="claimed",
                reason_code="lease_acquired",
                trace_id=claim_trace_id,
                now=current,
                actor_user_id=candidate.user_id,
                attempt_number=attempt_number,
            )
            await self._record_domain_event(
                job=candidate,
                action="claimed",
                status="claimed",
                reason_code="lease_acquired",
                trace_id=claim_trace_id,
                audit_event_id=audit.audit_event_id,
                now=current,
                attempt_number=attempt_number,
            )
            self.metrics.claims += 1
            self.metrics.claim_latency_ms_total += (
                datetime.now(UTC) - claim_started
            ).total_seconds() * 1_000
            return JobLease(
                job_run_id=candidate.id,
                attempt_id=attempt_id,
                delivery_id=delivery.delivery_id,
                worker_id=worker_id,
                lease_generation=generation,
                cancellation_generation=candidate.cancellation_generation,
                authority_generation=candidate.authority_generation or 0,
                source_version=candidate.source_version or 0,
                attempt_number=attempt_number,
                expires_at=expires_at,
            )
        return None

    async def renew(
        self,
        lease: JobLease,
        *,
        now: datetime | None = None,
    ) -> JobLease:
        current = _aware(now or datetime.now(UTC))
        job = await self._current_lease(lease, current)
        if not await self._scope_is_current(job):
            raise DurableJobConflictError("Job authority is no longer current.")
        expires_at = min(
            current + timedelta(seconds=self.lease_seconds),
            _aware(job.deadline_at)
            if job.deadline_at is not None
            else current + timedelta(seconds=self.lease_seconds),
        )
        updated = await self.session.scalar(
            update(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.id == lease.job_run_id,
                DocumentProcessingJob.locked_by == lease.worker_id,
                DocumentProcessingJob.lease_generation == lease.lease_generation,
                DocumentProcessingJob.cancellation_generation == lease.cancellation_generation,
                DocumentProcessingJob.lease_expires_at > current,
            )
            .values(lease_expires_at=expires_at, heartbeat_at=current)
            .returning(DocumentProcessingJob.id)
            .execution_options(synchronize_session=False)
        )
        if updated is None:
            self.metrics.lease_losses += 1
            raise DurableJobConflictError("Lease is no longer current.")
        return replace(lease, expires_at=expires_at)

    async def complete(
        self,
        lease: JobLease,
        *,
        result_id: uuid.UUID | None = None,
        publication_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> DurableJobOutcome:
        current = _aware(now or datetime.now(UTC))
        existing = await self.session.scalar(
            select(DurableJobOutcome).where(DurableJobOutcome.job_run_id == lease.job_run_id)
        )
        if existing is not None:
            if (
                existing.outcome != "succeeded"
                or existing.result_id != result_id
                or existing.publication_id != publication_id
            ):
                raise DurableJobConflictError("Job already has another terminal outcome.")
            return existing
        job = await self._current_lease(lease, current)
        await self._assert_protected_boundaries(job, lease, current)
        trace_id = uuid.uuid5(job.id, "outcome:succeeded")
        audit = await self._record_material(
            job=job,
            action="completed",
            status="succeeded",
            reason_code="job_completed",
            trace_id=trace_id,
            now=current,
            actor_user_id=job.user_id,
            attempt_number=lease.attempt_number,
        )
        domain_event = await self._record_domain_event(
            job=job,
            action="completed",
            status="succeeded",
            reason_code="job_completed",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            now=current,
            attempt_number=lease.attempt_number,
        )
        outcome = DurableJobOutcome(
            outcome_id=uuid.uuid5(job.id, "terminal-outcome"),
            job_run_id=job.id,
            attempt_id=lease.attempt_id,
            user_id=job.user_id,
            workspace_id=job.workspace_id,
            outcome="succeeded",
            result_id=result_id,
            publication_id=publication_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            domain_event_id=domain_event.event.event_id,
            recorded_at=current,
        )
        self.session.add(outcome)
        job.status = "succeeded"
        job.retryable = False
        job.completed_at = current
        job.result_id = result_id
        job.publication_id = publication_id
        self._clear_lease(job)
        await self.session.flush()
        return outcome

    async def fail(
        self,
        lease: JobLease,
        *,
        classification: RetryClassification,
        poison: bool = False,
        now: datetime | None = None,
    ) -> DurableRetryDecision:
        current = _aware(now or datetime.now(UTC))
        existing = await self.session.scalar(
            select(DurableRetryDecision).where(
                DurableRetryDecision.job_run_id == lease.job_run_id,
                DurableRetryDecision.attempt_number == lease.attempt_number,
            )
        )
        if existing is not None:
            if existing.failure_classification != classification.value:
                raise DurableJobConflictError("Retry classification changed on replay.")
            return existing
        job = await self._current_lease(lease, current)
        await self._assert_protected_boundaries(job, lease, current)
        retryable = classification in RETRYABLE_FAILURES and not poison
        attempts_exhausted = job.attempt_count >= job.max_attempts
        delay = self._full_jitter(job.id, job.attempt_count)
        eligible_at = current + delay
        deadline_exhausted = job.deadline_at is not None and eligible_at >= _aware(job.deadline_at)
        disposition = (
            "retry"
            if retryable and not attempts_exhausted and not deadline_exhausted
            else "dead_letter"
        )
        effective_classification = (
            RetryClassification.ATTEMPTS_EXHAUSTED
            if attempts_exhausted
            else RetryClassification.DEADLINE_EXCEEDED
            if deadline_exhausted
            else classification
        )
        decision = DurableRetryDecision(
            retry_decision_id=uuid.uuid5(job.id, f"retry:{lease.attempt_number}"),
            job_run_id=job.id,
            user_id=job.user_id,
            workspace_id=job.workspace_id,
            attempt_number=lease.attempt_number,
            failure_classification=effective_classification.value,
            disposition=disposition,
            delay_ms=int(delay.total_seconds() * 1_000) if disposition == "retry" else 0,
            jitter_digest=_digest(
                {
                    "jobRunId": str(job.id),
                    "attemptNumber": lease.attempt_number,
                    "delayMs": int(delay.total_seconds() * 1_000),
                }
            ),
            eligible_at=eligible_at if disposition == "retry" else None,
            decided_at=current,
        )
        self.session.add(decision)
        self._clear_lease(job)
        job.safe_error_category = effective_classification.value
        if disposition == "retry":
            sequence = await self._next_delivery_sequence(job.id)
            job.status = "retry_waiting"
            job.available_at = eligible_at
            self.session.add(
                DurableQueueDelivery(
                    delivery_id=uuid.uuid5(job.id, f"delivery:{sequence}"),
                    job_run_id=job.id,
                    user_id=job.user_id,
                    workspace_id=job.workspace_id,
                    delivery_sequence=sequence,
                    delivery_kind="retry",
                    idempotency_key=f"job:{job.id}:delivery:{sequence}",
                    eligible_at=eligible_at,
                    created_at=current,
                )
            )
            retry_trace_id = uuid.uuid5(job.id, f"retry-trace:{lease.attempt_number}")
            audit = await self._record_material(
                job=job,
                action="retry_scheduled",
                status="retry_waiting",
                reason_code=effective_classification.value,
                trace_id=retry_trace_id,
                now=current,
                actor_user_id=job.user_id,
                attempt_number=lease.attempt_number,
            )
            await self._record_domain_event(
                job=job,
                action="retry_scheduled",
                status="retry_waiting",
                reason_code=effective_classification.value,
                trace_id=retry_trace_id,
                audit_event_id=audit.audit_event_id,
                now=current,
                attempt_number=lease.attempt_number,
            )
            self.metrics.retries += 1
        else:
            await self._dead_letter(
                job,
                lease=lease,
                classification=effective_classification,
                reason_code="poison_job" if poison else effective_classification.value,
                now=current,
            )
        await self.session.flush()
        return decision

    async def cancel(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        job_run_id: uuid.UUID,
        reason_code: str,
        now: datetime | None = None,
    ) -> JobView:
        current = _aware(now or datetime.now(UTC))
        job = await self._owned_job(job_run_id, workspace_id)
        decision = await CollaborationAuthorizationService(self.session).evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.RESOURCE_EDIT,
            expected_authority_generation=job.authority_generation,
        )
        if not decision.allowed or principal.user_id != job.user_id:
            raise DurableJobNotFoundError()
        if job.status in TERMINAL_STATES:
            return _view(job)
        job.cancellation_generation += 1
        job.status = "cancelled"
        job.retryable = False
        job.completed_at = current
        self._clear_lease(job)
        trace_id = uuid.uuid5(job.id, f"cancel:{job.cancellation_generation}")
        audit = await self._record_material(
            job=job,
            action="canceled",
            status="cancelled",
            reason_code=_safe_reason(reason_code),
            trace_id=trace_id,
            now=current,
            actor_user_id=principal.user_id,
        )
        domain_event = await self._record_domain_event(
            job=job,
            action="canceled",
            status="cancelled",
            reason_code=_safe_reason(reason_code),
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            now=current,
        )
        self.session.add(
            DurableJobOutcome(
                outcome_id=uuid.uuid5(job.id, "terminal-outcome"),
                job_run_id=job.id,
                attempt_id=None,
                user_id=job.user_id,
                workspace_id=job.workspace_id,
                outcome="canceled",
                failure_classification="canceled",
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                domain_event_id=domain_event.event.event_id,
                recorded_at=current,
            )
        )
        self.metrics.cancellations += 1
        await self.session.flush()
        return _view(job)

    async def recover_expired(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        current = _aware(now or datetime.now(UTC))
        if not 1 <= limit <= 1_000:
            raise DurableJobValidationError("Recovery limit is invalid.")
        jobs = list(
            (
                await self.session.scalars(
                    select(DocumentProcessingJob)
                    .where(
                        DocumentProcessingJob.status == "claimed",
                        DocumentProcessingJob.lease_expires_at <= current,
                        DocumentProcessingJob.completed_at.is_(None),
                    )
                    .order_by(DocumentProcessingJob.lease_expires_at, DocumentProcessingJob.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        recovered = 0
        for job in jobs:
            attempt_number = job.attempt_count
            attempt = await self.session.scalar(
                select(DurableJobAttempt).where(
                    DurableJobAttempt.job_run_id == job.id,
                    DurableJobAttempt.attempt_number == attempt_number,
                )
            )
            if attempt is None:
                raise DurableJobConflictError("Expired job has no durable attempt evidence.")
            if (
                attempt.delivery_id is None
                or attempt.worker_id is None
                or job.lease_expires_at is None
            ):
                raise DurableJobConflictError("Expired job has incomplete lease evidence.")
            decision = await self.session.scalar(
                select(DurableRetryDecision).where(
                    DurableRetryDecision.job_run_id == job.id,
                    DurableRetryDecision.attempt_number == attempt_number,
                )
            )
            attempts_exhausted = attempt_number >= job.max_attempts
            deadline_exhausted = job.deadline_at is not None and _aware(job.deadline_at) <= current
            if attempts_exhausted or deadline_exhausted:
                classification = (
                    RetryClassification.ATTEMPTS_EXHAUSTED
                    if attempts_exhausted
                    else RetryClassification.DEADLINE_EXCEEDED
                )
                if decision is None:
                    self.session.add(
                        DurableRetryDecision(
                            retry_decision_id=uuid.uuid5(job.id, f"retry:{attempt_number}"),
                            job_run_id=job.id,
                            user_id=job.user_id,
                            workspace_id=job.workspace_id,
                            attempt_number=attempt_number,
                            failure_classification=classification.value,
                            disposition="dead_letter",
                            delay_ms=0,
                            jitter_digest=_digest(
                                {
                                    "jobRunId": str(job.id),
                                    "attemptNumber": attempt_number,
                                    "delayMs": 0,
                                }
                            ),
                            eligible_at=None,
                            decided_at=current,
                        )
                    )
                await self._dead_letter(
                    job,
                    lease=JobLease(
                        job_run_id=job.id,
                        attempt_id=attempt.attempt_id,
                        delivery_id=attempt.delivery_id,
                        worker_id=attempt.worker_id,
                        lease_generation=attempt.lease_generation,
                        cancellation_generation=job.cancellation_generation,
                        authority_generation=job.authority_generation or 0,
                        source_version=job.source_version or 0,
                        attempt_number=attempt_number,
                        expires_at=_aware(job.lease_expires_at),
                    ),
                    classification=classification,
                    reason_code=classification.value,
                    now=current,
                )
                recovered += 1
                self.metrics.lease_losses += 1
                self.metrics.recovered_leases += 1
                continue
            if decision is None:
                self.session.add(
                    DurableRetryDecision(
                        retry_decision_id=uuid.uuid5(
                            job.id,
                            f"retry:{attempt_number}",
                        ),
                        job_run_id=job.id,
                        user_id=job.user_id,
                        workspace_id=job.workspace_id,
                        attempt_number=attempt_number,
                        failure_classification=RetryClassification.LEASE_INTERRUPTED.value,
                        disposition="retry",
                        delay_ms=0,
                        jitter_digest=_digest(
                            {
                                "jobRunId": str(job.id),
                                "attemptNumber": attempt_number,
                                "delayMs": 0,
                            }
                        ),
                        eligible_at=current,
                        decided_at=current,
                    )
                )
            sequence = await self._next_delivery_sequence(job.id)
            job.status = "retry_waiting"
            job.available_at = current
            job.lease_generation += 1
            self._clear_lease(job)
            self.session.add(
                DurableQueueDelivery(
                    delivery_id=uuid.uuid5(job.id, f"delivery:{sequence}"),
                    job_run_id=job.id,
                    user_id=job.user_id,
                    workspace_id=job.workspace_id,
                    delivery_sequence=sequence,
                    delivery_kind="recovery",
                    idempotency_key=f"job:{job.id}:delivery:{sequence}",
                    eligible_at=current,
                    created_at=current,
                )
            )
            trace_id = uuid.uuid5(job.id, f"recovery:{job.lease_generation}")
            audit = await self._record_material(
                job=job,
                action="retry_scheduled",
                status="retry_waiting",
                reason_code="lease_interrupted",
                trace_id=trace_id,
                now=current,
                actor_user_id=job.user_id,
                attempt_number=attempt_number,
            )
            await self._record_domain_event(
                job=job,
                action="retry_scheduled",
                status="retry_waiting",
                reason_code="lease_interrupted",
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                now=current,
                attempt_number=attempt_number,
            )
            recovered += 1
            self.metrics.lease_losses += 1
            self.metrics.recovered_leases += 1
        await self.session.flush()
        return recovered

    async def reconcile_deadlines(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        current = _aware(now or datetime.now(UTC))
        if not 1 <= limit <= 1_000:
            raise DurableJobValidationError("Reconciliation limit is invalid.")
        jobs = list(
            (
                await self.session.scalars(
                    select(DocumentProcessingJob)
                    .where(
                        DocumentProcessingJob.status.in_(ACTIVE_STATES),
                        DocumentProcessingJob.deadline_at <= current,
                        DocumentProcessingJob.completed_at.is_(None),
                        DocumentProcessingJob.legacy_backfill.is_(False),
                    )
                    .order_by(DocumentProcessingJob.deadline_at, DocumentProcessingJob.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for job in jobs:
            job.cancellation_generation += 1
            job.lease_generation += 1
            await self._terminalize_without_lease(
                job,
                outcome="deadline_expired",
                status="permanent_failure",
                reason_code="deadline_exceeded",
                now=current,
            )
            self.metrics.deadline_expirations += 1
        await self.session.flush()
        return len(jobs)

    async def refresh_backlog_metrics(self, *, now: datetime | None = None) -> None:
        current = _aware(now or datetime.now(UTC))
        queue_depth, oldest_created_at = (
            await self.session.execute(
                select(
                    func.count(DocumentProcessingJob.id),
                    func.min(DocumentProcessingJob.created_at),
                ).where(
                    DocumentProcessingJob.status.in_(CLAIMABLE_STATES),
                    DocumentProcessingJob.completed_at.is_(None),
                    DocumentProcessingJob.legacy_backfill.is_(False),
                )
            )
        ).one()
        self.metrics.queue_depth = int(queue_depth or 0)
        self.metrics.oldest_queue_age_seconds = (
            max(0.0, (current - _aware(oldest_created_at)).total_seconds())
            if oldest_created_at is not None
            else 0.0
        )

    async def list_dead_letters(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        limit: int = 50,
    ) -> list[DurableJobDeadLetter]:
        if not 1 <= limit <= 100:
            raise DurableJobValidationError("Dead-letter limit is invalid.")
        decision = await CollaborationAuthorizationService(self.session).evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.WORKSPACE_SETTINGS_MANAGE,
        )
        if not decision.allowed:
            raise DurableJobNotFoundError()
        return list(
            (
                await self.session.scalars(
                    select(DurableJobDeadLetter)
                    .where(DurableJobDeadLetter.workspace_id == workspace_id)
                    .order_by(
                        DurableJobDeadLetter.created_at.desc(),
                        DurableJobDeadLetter.dead_letter_id.desc(),
                    )
                    .limit(limit)
                )
            ).all()
        )

    async def replay(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        dead_letter_id: uuid.UUID,
        reason_code: Literal["operator_retry", "dependency_recovered", "policy_corrected"],
        idempotency_key: str,
        now: datetime | None = None,
    ) -> DocumentProcessingJob:
        current = _aware(now or datetime.now(UTC))
        if not idempotency_key.strip() or len(idempotency_key) > 160:
            raise DurableJobValidationError("Idempotency key is invalid.")
        dead = await self.session.scalar(
            select(DurableJobDeadLetter).where(
                DurableJobDeadLetter.dead_letter_id == dead_letter_id,
                DurableJobDeadLetter.workspace_id == workspace_id,
            )
        )
        if dead is None:
            raise DurableJobNotFoundError()
        source = await self._owned_job(dead.job_run_id, workspace_id)
        decision = await CollaborationAuthorizationService(self.session).evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.WORKSPACE_SETTINGS_MANAGE,
        )
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.authority_generation is None
            or source.canvas_id is None
            or source.document_version_id is None
        ):
            raise DurableJobNotFoundError()
        if await self._boundary_failure(source) is not None:
            raise DurableJobConflictError("Replay source or authority is no longer current.")
        request_digest = _digest(
            {
                "deadLetterId": str(dead_letter_id),
                "sourceJobRunId": str(source.id),
                "requester": str(principal.user_id),
                "reasonCode": reason_code,
                "authorityGeneration": decision.authority_generation,
            }
        )
        existing_request = await self.session.scalar(
            select(DurableJobRequest).where(
                DurableJobRequest.user_id == principal.user_id,
                DurableJobRequest.workspace_id == workspace_id,
                DurableJobRequest.idempotency_key == idempotency_key,
            )
        )
        if existing_request is not None:
            if existing_request.request_digest != request_digest:
                raise DurableJobConflictError("Replay idempotency identity was reused.")
            existing_job = await self.session.scalar(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.request_id == existing_request.request_id
                )
            )
            if existing_job is None:
                raise DurableJobConflictError("Replay request is incomplete.")
            return existing_job
        request_id = uuid.uuid5(
            dead_letter_id,
            f"replay:{principal.user_id}:{idempotency_key}",
        )
        new_job_id = uuid.uuid5(request_id, "job-run")
        trace_id = uuid.uuid5(request_id, "trace")
        run_number = (
            await self.session.scalar(
                select(func.coalesce(func.max(DocumentProcessingJob.attempt), 0)).where(
                    DocumentProcessingJob.document_id == source.document_id
                )
            )
            or 0
        ) + 1
        request = DurableJobRequest(
            request_id=request_id,
            user_id=principal.user_id,
            membership_id=decision.membership_id,
            workspace_id=workspace_id,
            canvas_id=source.canvas_id,
            document_id=source.document_id,
            document_version_id=source.document_version_id,
            request_kind=source.job_kind,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            authority_generation=decision.authority_generation,
            cancellation_generation=0,
            trace_id=trace_id,
            created_at=current,
        )
        job = DocumentProcessingJob(
            id=new_job_id,
            request_id=request_id,
            user_id=principal.user_id,
            membership_id=decision.membership_id,
            workspace_id=workspace_id,
            canvas_id=source.canvas_id,
            document_id=source.document_id,
            document_version_id=source.document_version_id,
            job_kind=source.job_kind,
            attempt=run_number,
            attempt_count=0,
            max_attempts=source.max_attempts,
            status="queued",
            idempotency_key=f"job:{new_job_id}",
            request_digest=request_digest,
            authority_generation=decision.authority_generation,
            cancellation_generation=0,
            source_version=source.source_version,
            priority_class=source.priority_class,
            priority=source.priority,
            eligibility_class="operator_replay",
            available_at=current,
            deadline_at=current + timedelta(hours=1),
            retryable=True,
        )
        delivery = DurableQueueDelivery(
            delivery_id=uuid.uuid5(new_job_id, "delivery:1"),
            job_run_id=new_job_id,
            user_id=principal.user_id,
            workspace_id=workspace_id,
            delivery_sequence=1,
            delivery_kind="replay",
            idempotency_key=f"job:{new_job_id}:delivery:1",
            eligible_at=current,
            created_at=current,
        )
        audit_id = uuid.uuid5(new_job_id, "audit:replayed")
        replay = DurableJobReplayRequest(
            replay_request_id=uuid.uuid5(new_job_id, "replay-request"),
            dead_letter_id=dead_letter_id,
            source_job_run_id=source.id,
            new_job_run_id=new_job_id,
            requested_by_user_id=principal.user_id,
            membership_id=decision.membership_id,
            workspace_id=workspace_id,
            canvas_id=source.canvas_id,
            authority_generation=decision.authority_generation,
            reason_code=reason_code,
            trace_id=trace_id,
            audit_event_id=audit_id,
            created_at=current,
        )
        audit = DurableJobAuditEvent(
            audit_event_id=audit_id,
            job_run_id=new_job_id,
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            action="replayed",
            outcome="succeeded",
            reason_code=reason_code,
            metadata_digest=_digest(
                {"sourceJobRunId": str(source.id), "deadLetterId": str(dead_letter_id)}
            ),
            trace_id=trace_id,
            recorded_at=current,
        )
        self.session.add(request)
        await self.session.flush()
        self.session.add(job)
        await self.session.flush()
        self.session.add_all((delivery, replay, audit))
        await TraceService(self.session).record_event(
            RecordTraceEventInput(
                trace_id=trace_id,
                event_type="durable_job.replayed",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=new_job_id,
                object_type="durable_job",
                operation="replay",
                status="succeeded",
                metadata={"reasonCode": reason_code},
            )
        )
        await self._record_domain_event(
            job=job,
            action="replayed",
            status="queued",
            reason_code=reason_code,
            trace_id=trace_id,
            audit_event_id=audit_id,
            now=current,
        )
        self.metrics.replays += 1
        await self.session.flush()
        return job

    async def get_status(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        job_run_id: uuid.UUID,
    ) -> JobView:
        job = await self._owned_job(job_run_id, workspace_id)
        decision = await CollaborationAuthorizationService(self.session).evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.RESOURCE_VIEW,
        )
        if not decision.allowed or job.user_id != principal.user_id:
            raise DurableJobNotFoundError()
        return _view(job)

    async def _dead_letter(
        self,
        job: DocumentProcessingJob,
        *,
        lease: JobLease,
        classification: RetryClassification,
        reason_code: str,
        now: datetime,
    ) -> None:
        normalized_reason = (
            reason_code
            if reason_code
            in {
                "poison_job",
                "attempts_exhausted",
                "deadline_exceeded",
                "terminal_failure",
                "authority_revoked",
                "source_superseded",
            }
            else "terminal_failure"
        )
        trace_id = uuid.uuid5(job.id, "dead-letter")
        audit = await self._record_material(
            job=job,
            action="dead_lettered",
            status="dead_lettered",
            reason_code=normalized_reason,
            trace_id=trace_id,
            now=now,
            actor_user_id=job.user_id,
            attempt_number=lease.attempt_number,
        )
        event = await self._record_domain_event(
            job=job,
            action="dead_lettered",
            status="dead_lettered",
            reason_code=normalized_reason,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            now=now,
            attempt_number=lease.attempt_number,
        )
        self.session.add(
            DurableJobDeadLetter(
                dead_letter_id=uuid.uuid5(job.id, "dead-letter"),
                job_run_id=job.id,
                attempt_id=lease.attempt_id,
                user_id=job.user_id,
                workspace_id=job.workspace_id,
                reason_code=normalized_reason,
                failure_classification=classification.value,
                authority_generation=job.authority_generation,
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                created_at=now,
            )
        )
        self.session.add(
            DurableJobOutcome(
                outcome_id=uuid.uuid5(job.id, "terminal-outcome"),
                job_run_id=job.id,
                attempt_id=lease.attempt_id,
                user_id=job.user_id,
                workspace_id=job.workspace_id,
                outcome="dead_lettered",
                failure_classification=classification.value,
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                domain_event_id=event.event.event_id,
                recorded_at=now,
            )
        )
        job.status = "dead_lettered"
        job.retryable = False
        job.completed_at = now
        self._clear_lease(job)
        self.metrics.dead_letters += 1

    async def _terminalize_without_lease(
        self,
        job: DocumentProcessingJob,
        *,
        outcome: Literal["failed", "authority_revoked", "deadline_expired"],
        status: str,
        reason_code: str,
        now: datetime,
    ) -> None:
        if await self.session.scalar(
            select(DurableJobOutcome.outcome_id).where(DurableJobOutcome.job_run_id == job.id)
        ):
            return
        trace_id = uuid.uuid5(job.id, f"terminal:{outcome}")
        audit = await self._record_material(
            job=job,
            action="failed",
            status=status,
            reason_code=reason_code,
            trace_id=trace_id,
            now=now,
            actor_user_id=job.user_id,
        )
        event = await self._record_domain_event(
            job=job,
            action="failed",
            status=status,
            reason_code=reason_code,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            now=now,
        )
        self.session.add(
            DurableJobOutcome(
                outcome_id=uuid.uuid5(job.id, "terminal-outcome"),
                job_run_id=job.id,
                attempt_id=None,
                user_id=job.user_id,
                workspace_id=job.workspace_id,
                outcome=outcome,
                failure_classification=reason_code,
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                domain_event_id=event.event.event_id,
                recorded_at=now,
            )
        )
        job.status = status
        job.safe_error_category = reason_code
        job.completed_at = now
        job.retryable = False
        self._clear_lease(job)

    async def _current_lease(
        self,
        lease: JobLease,
        current: datetime,
    ) -> DocumentProcessingJob:
        job = await self.session.scalar(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.id == lease.job_run_id,
                DocumentProcessingJob.locked_by == lease.worker_id,
                DocumentProcessingJob.lease_generation == lease.lease_generation,
                DocumentProcessingJob.cancellation_generation == lease.cancellation_generation,
                DocumentProcessingJob.status.in_(
                    (
                        "claimed",
                        "processing",
                        "extracting",
                        "chunking",
                        "embedding",
                        "indexing",
                    )
                ),
                DocumentProcessingJob.completed_at.is_(None),
                DocumentProcessingJob.lease_expires_at > current,
            )
        )
        if job is None:
            self.metrics.stale_results_suppressed += 1
            raise DurableJobConflictError("Stale, expired, or canceled lease.")
        return job

    async def _assert_protected_boundaries(
        self,
        job: DocumentProcessingJob,
        lease: JobLease,
        current: datetime,
    ) -> None:
        if job.deadline_at is not None and _aware(job.deadline_at) <= current:
            raise DurableJobConflictError("Job deadline expired.")
        if job.authority_generation != lease.authority_generation:
            raise DurableJobConflictError("Job authority generation changed.")
        if job.source_version != lease.source_version:
            raise DurableJobConflictError("Job source version changed.")
        if not await self._scope_is_current(job):
            raise DurableJobConflictError("Job authority is no longer current.")
        version = await self.session.get(DocumentVersion, job.document_version_id)
        current_source_version = await self.session.scalar(
            select(Document.current_version).where(
                Document.id == job.document_id,
                Document.deleted_at.is_(None),
            )
        )
        if (
            version is None
            or version.deleted_at is not None
            or version.version != lease.source_version
            or current_source_version != lease.source_version
        ):
            raise DurableJobConflictError("Job source version is no longer publishable.")

    async def _scope_is_current(self, job: DocumentProcessingJob) -> bool:
        return await self._boundary_failure(job) is None

    async def _boundary_failure(self, job: DocumentProcessingJob) -> str | None:
        if (
            job.membership_id is None
            or job.authority_generation is None
            or job.canvas_id is None
            or job.document_version_id is None
            or job.source_version is None
        ):
            return "authority_revoked"
        authority = await self.session.get(WorkspaceAuthorityVersion, job.workspace_id)
        if authority is None or authority.authority_generation != job.authority_generation:
            return "authority_revoked"
        latest = await self.session.scalar(
            select(WorkspaceMembershipTransition)
            .where(
                WorkspaceMembershipTransition.membership_id == job.membership_id,
                WorkspaceMembershipTransition.user_id == job.user_id,
                WorkspaceMembershipTransition.workspace_id == job.workspace_id,
            )
            .order_by(WorkspaceMembershipTransition.sequence.desc())
            .limit(1)
        )
        membership = await self.session.get(WorkspaceMembership, job.membership_id)
        if not (
            membership is not None
            and latest is not None
            and latest.current_state == "active"
            and latest.authority_generation <= job.authority_generation
        ):
            return "authority_revoked"
        source = await self.session.scalar(
            select(DocumentVersion.id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(Canvas, Canvas.id == Document.canvas_id)
            .where(
                DocumentVersion.id == job.document_version_id,
                DocumentVersion.document_id == job.document_id,
                DocumentVersion.version == job.source_version,
                DocumentVersion.deleted_at.is_(None),
                Document.current_version == job.source_version,
                Document.deleted_at.is_(None),
                Document.canvas_id == job.canvas_id,
                Canvas.workspace_id == job.workspace_id,
            )
        )
        return None if source is not None else "source_superseded"

    async def _owned_job(
        self,
        job_run_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> DocumentProcessingJob:
        job = await self.session.scalar(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.id == job_run_id,
                DocumentProcessingJob.workspace_id == workspace_id,
                DocumentProcessingJob.legacy_backfill.is_(False),
            )
        )
        if job is None:
            raise DurableJobNotFoundError()
        return job

    async def _current_delivery(
        self,
        job_run_id: uuid.UUID,
        current: datetime,
    ) -> DurableQueueDelivery | None:
        return cast(
            DurableQueueDelivery | None,
            await self.session.scalar(
                select(DurableQueueDelivery)
                .where(
                    DurableQueueDelivery.job_run_id == job_run_id,
                    DurableQueueDelivery.eligible_at <= current,
                )
                .order_by(DurableQueueDelivery.delivery_sequence.desc())
                .limit(1)
            ),
        )

    async def _next_delivery_sequence(self, job_run_id: uuid.UUID) -> int:
        return (
            await self.session.scalar(
                select(func.coalesce(func.max(DurableQueueDelivery.delivery_sequence), 0)).where(
                    DurableQueueDelivery.job_run_id == job_run_id
                )
            )
            or 0
        ) + 1

    def _full_jitter(self, job_run_id: uuid.UUID, attempt_number: int) -> timedelta:
        ceiling = min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2 ** max(0, attempt_number - 1)),
        )
        seed = int.from_bytes(
            hashlib.sha256(f"{job_run_id}:{attempt_number}".encode()).digest()[:8],
            "big",
        )
        return timedelta(seconds=random.Random(seed).uniform(0, ceiling))

    async def _record_material(
        self,
        *,
        job: DocumentProcessingJob,
        action: str,
        status: str,
        reason_code: str,
        trace_id: uuid.UUID,
        now: datetime,
        actor_user_id: uuid.UUID,
        attempt_number: int | None = None,
    ) -> DurableJobAuditEvent:
        audit_id = uuid.uuid5(trace_id, "audit")
        audit = DurableJobAuditEvent(
            audit_event_id=audit_id,
            job_run_id=job.id,
            workspace_id=job.workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            outcome="succeeded",
            reason_code=_safe_reason(reason_code),
            metadata_digest=_digest(
                {
                    "status": status,
                    "attemptNumber": attempt_number,
                    "leaseGeneration": job.lease_generation,
                    "cancellationGeneration": job.cancellation_generation,
                    "authorityGeneration": job.authority_generation,
                    "sourceVersion": job.source_version,
                }
            ),
            trace_id=trace_id,
            recorded_at=now,
        )
        self.session.add(audit)
        await TraceService(self.session).record_event(
            RecordTraceEventInput(
                trace_id=trace_id,
                event_type=f"durable_job.{action}",
                actor_id=str(actor_user_id),
                actor_type="user" if action in {"created", "canceled", "replayed"} else "service",
                user_id=job.user_id,
                workspace_id=job.workspace_id,
                object_id=job.id,
                object_type="durable_job",
                operation=action,
                status="succeeded",
                metadata={
                    "status": status,
                    "reasonCode": _safe_reason(reason_code),
                    "attemptNumber": attempt_number,
                    "leaseGeneration": job.lease_generation,
                },
            )
        )
        await self.session.flush()
        return audit

    async def _record_domain_event(
        self,
        *,
        job: DocumentProcessingJob,
        action: str,
        status: str,
        reason_code: str,
        trace_id: uuid.UUID,
        audit_event_id: uuid.UUID,
        now: datetime,
        attempt_number: int | None = None,
    ) -> RecordedDomainEvent:
        owner_user_id = await self.session.scalar(
            select(Workspace.owner_id).where(Workspace.id == job.workspace_id)
        )
        if owner_user_id is None:
            raise DurableJobNotFoundError()
        return await DomainEventService(self.session).record(
            CreateDomainEvent(
                event_type=f"job.{action}",
                user_id=owner_user_id,
                workspace_id=job.workspace_id,
                canvas_id=job.canvas_id,
                subject_id=job.id,
                actor_user_id=job.user_id,
                source_identity=(
                    f"durable-job:{job.id}:{action}:{job.lease_generation}:"
                    f"{job.cancellation_generation}"
                ),
                trace_id=trace_id,
                audit_event_id=audit_event_id,
                payload={
                    "status": status,
                    "reasonCode": _safe_reason(reason_code),
                    "attemptNumber": attempt_number,
                    "leaseGeneration": job.lease_generation,
                    "cancellationGeneration": job.cancellation_generation,
                    "authorityGeneration": job.authority_generation,
                    "sourceVersion": job.source_version,
                    "jobKind": job.job_kind,
                },
                origin_type="canonical_service",
                occurred_at=now,
            )
        )

    @staticmethod
    def _clear_lease(job: DocumentProcessingJob) -> None:
        job.locked_by = None
        job.lease_expires_at = None
        job.heartbeat_at = None


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _safe_reason(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if not normalized or len(normalized) > 64:
        raise DurableJobValidationError("Reason code is invalid.")
    return normalized


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _view(job: DocumentProcessingJob) -> JobView:
    return JobView(
        job_run_id=job.id,
        request_id=job.request_id,
        workspace_id=job.workspace_id,
        canvas_id=job.canvas_id,
        document_id=job.document_id,
        document_version_id=job.document_version_id,
        status=job.status,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        available_at=job.available_at,
        deadline_at=job.deadline_at,
        completed_at=job.completed_at,
        safe_error_category=job.safe_error_category,
        cancellation_generation=job.cancellation_generation,
    )


__all__ = [
    "ACTIVE_STATES",
    "CLAIMABLE_STATES",
    "RETRYABLE_FAILURES",
    "DurableJobConflictError",
    "DurableJobError",
    "DurableJobMetrics",
    "DurableJobNotFoundError",
    "DurableJobService",
    "DurableJobUnavailableError",
    "DurableJobValidationError",
    "JobLease",
    "JobView",
    "RetryClassification",
]
