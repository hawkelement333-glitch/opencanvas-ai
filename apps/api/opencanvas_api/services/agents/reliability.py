from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import JsonValue
from sqlalchemy import or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    ControlledAgentExecution,
    ControlledAgentReversibleWriteEffect,
)
from opencanvas_api.services.agents.contracts import (
    ApprovalDecision,
    ApprovalRecord,
    AuditAttribute,
    AuditEvent,
    CapabilityGrant,
    ExecutionStateRecord,
    ExecutionStatus,
)
from opencanvas_api.services.agents.persistence import (
    AgentPersistenceNotFound,
    ControlledAgentRepository,
)
from opencanvas_api.services.trace import RecordTraceEventInput, TraceService

EXECUTION_LEASE_DURATION = timedelta(minutes=1)
RETRY_BASE_DELAY = timedelta(seconds=5)
RETRY_MAX_DELAY = timedelta(minutes=1)


class RetryFailureClassification(StrEnum):
    """Closed server-owned retry vocabulary."""

    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    STORAGE_TEMPORARILY_UNAVAILABLE = "storage_temporarily_unavailable"
    AUTHORITY_INVALID = "authority_invalid"
    ACTION_CONFLICT = "action_conflict"
    ACTION_INVALID = "action_invalid"
    UNSUPPORTED_ACTION = "unsupported_action"


RETRYABLE_FAILURES = frozenset(
    {
        RetryFailureClassification.PROVIDER_TIMEOUT,
        RetryFailureClassification.PROVIDER_UNAVAILABLE,
        RetryFailureClassification.STORAGE_TEMPORARILY_UNAVAILABLE,
    }
)


class RetryActionError(RuntimeError):
    """Trusted internal action-adapter failure with a closed classification."""

    def __init__(self, classification: RetryFailureClassification) -> None:
        super().__init__(classification.value)
        self.classification = classification


class ExecutionReliabilityDenied(RuntimeError):
    """Safe closed-domain result for an invalid execution ownership operation."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    execution_id: uuid.UUID
    owner_id: str
    generation: int
    acquired_at: datetime
    expires_at: datetime
    attempt_count: int
    trace_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExecutionLeaseChange:
    execution_id: uuid.UUID
    generation: int
    expires_at: datetime | None
    attempt_count: int
    trace_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExecutionRecovery:
    execution_id: uuid.UUID
    superseded_generation: int
    generation: int
    next_retry_at: datetime
    attempt_count: int
    trace_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class RetryExecutionResult:
    execution_id: uuid.UUID
    status: ExecutionStatus
    attempt_count: int
    failure_classification: str | None
    next_retry_at: datetime | None
    duplicate: bool
    trace_id: uuid.UUID


class ControlledExecutionReliability:
    """Internal compare-and-set boundary for bounded execution ownership."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        trace_service: TraceService | None = None,
    ) -> None:
        self.session = session
        self.repository = ControlledAgentRepository(session)
        self.trace_service = trace_service or TraceService(session)

    async def claim(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        claimed_at: datetime,
    ) -> ExecutionLease:
        claimed_at = _aware_utc(claimed_at)
        trace_id = uuid.uuid4()
        owner_id = str(uuid.uuid4())
        lease_expires_at: datetime
        async with self.session.begin_nested():
            await self._validate_claim_authority(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                evaluated_at=claimed_at,
            )
            current = await self.repository.current_state(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
            )
            if current is None or ExecutionStatus(current.status) is not ExecutionStatus.READY:
                raise ExecutionReliabilityDenied("execution_not_claimable")
            execution = await self.repository._owned_execution(
                user_id,
                workspace_id,
                execution_id,
            )
            deadline_at = _aware_utc(execution.deadline_at)
            lease_expires_at = min(claimed_at + EXECUTION_LEASE_DURATION, deadline_at)
            if lease_expires_at <= claimed_at:
                raise ExecutionReliabilityDenied("execution_deadline_expired")

            try:
                claimed_id = await self.session.scalar(
                    update(ControlledAgentExecution)
                    .where(
                        ControlledAgentExecution.id == execution_id,
                        ControlledAgentExecution.user_id == user_id,
                        ControlledAgentExecution.workspace_id == workspace_id,
                        ControlledAgentExecution.completed_at.is_(None),
                        ControlledAgentExecution.deadline_at > claimed_at,
                        ControlledAgentExecution.attempt_count
                        < ControlledAgentExecution.max_attempts,
                        or_(
                            ControlledAgentExecution.next_retry_at.is_(None),
                            ControlledAgentExecution.next_retry_at <= claimed_at,
                        ),
                        or_(
                            ControlledAgentExecution.lease_owner_id.is_(None),
                            ControlledAgentExecution.lease_expires_at <= claimed_at,
                        ),
                    )
                    .values(
                        lease_owner_id=owner_id,
                        lease_acquired_at=claimed_at,
                        lease_expires_at=lease_expires_at,
                        lease_generation=ControlledAgentExecution.lease_generation + 1,
                        attempt_count=ControlledAgentExecution.attempt_count + 1,
                        next_retry_at=None,
                    )
                    .returning(ControlledAgentExecution.id)
                    .execution_options(synchronize_session=False)
                )
            except OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                raise ExecutionReliabilityDenied("execution_claim_conflict") from None
            if claimed_id is None:
                raise ExecutionReliabilityDenied(
                    await self._claim_denial_reason(execution_id, user_id, workspace_id, claimed_at)
                )
            await self.session.refresh(execution)
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=execution_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    status=ExecutionStatus.RUNNING,
                    recorded_at=claimed_at,
                )
            )
            await self._record_event(
                trace_id=trace_id,
                execution=execution,
                event_type="execution.lease_claimed",
                recorded_at=claimed_at,
                metadata={
                    "attemptCount": execution.attempt_count,
                    "leaseGeneration": execution.lease_generation,
                    "leaseExpiresAt": lease_expires_at.isoformat(),
                },
            )
        return ExecutionLease(
            execution_id=execution_id,
            owner_id=owner_id,
            generation=execution.lease_generation,
            acquired_at=claimed_at,
            expires_at=lease_expires_at,
            attempt_count=execution.attempt_count,
            trace_id=trace_id,
        )

    async def renew(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        owner_id: str,
        generation: int,
        renewed_at: datetime,
    ) -> ExecutionLeaseChange:
        renewed_at = _aware_utc(renewed_at)
        if not owner_id or generation < 1:
            raise ExecutionReliabilityDenied("lease_identity_invalid")
        trace_id = uuid.uuid4()
        async with self.session.begin_nested():
            await self._validate_claim_authority(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                evaluated_at=renewed_at,
            )
            current = await self.repository.current_state(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
            )
            if current is None or ExecutionStatus(current.status) is not ExecutionStatus.RUNNING:
                raise ExecutionReliabilityDenied("execution_not_running")
            execution = await self.repository._owned_execution(
                user_id,
                workspace_id,
                execution_id,
            )
            deadline_at = _aware_utc(execution.deadline_at)
            expires_at = min(renewed_at + EXECUTION_LEASE_DURATION, deadline_at)
            if expires_at <= renewed_at:
                raise ExecutionReliabilityDenied("execution_deadline_expired")
            renewed_id = await self.session.scalar(
                update(ControlledAgentExecution)
                .where(
                    ControlledAgentExecution.id == execution_id,
                    ControlledAgentExecution.user_id == user_id,
                    ControlledAgentExecution.workspace_id == workspace_id,
                    ControlledAgentExecution.completed_at.is_(None),
                    ControlledAgentExecution.deadline_at > renewed_at,
                    ControlledAgentExecution.lease_owner_id == owner_id,
                    ControlledAgentExecution.lease_generation == generation,
                    ControlledAgentExecution.lease_expires_at > renewed_at,
                )
                .values(lease_expires_at=expires_at)
                .returning(ControlledAgentExecution.id)
                .execution_options(synchronize_session=False)
            )
            if renewed_id is None:
                raise ExecutionReliabilityDenied("lease_not_current")
            await self.session.refresh(execution)
            await self._record_event(
                trace_id=trace_id,
                execution=execution,
                event_type="execution.lease_renewed",
                recorded_at=renewed_at,
                metadata={
                    "attemptCount": execution.attempt_count,
                    "leaseGeneration": execution.lease_generation,
                    "leaseExpiresAt": expires_at.isoformat(),
                },
            )
        return ExecutionLeaseChange(
            execution_id=execution_id,
            generation=execution.lease_generation,
            expires_at=expires_at,
            attempt_count=execution.attempt_count,
            trace_id=trace_id,
        )

    async def release(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        owner_id: str,
        generation: int,
        released_at: datetime,
    ) -> ExecutionLeaseChange:
        released_at = _aware_utc(released_at)
        if not owner_id or generation < 1:
            raise ExecutionReliabilityDenied("lease_identity_invalid")
        trace_id = uuid.uuid4()
        async with self.session.begin_nested():
            current = await self.repository.current_state(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
            )
            if current is None or ExecutionStatus(current.status) is not ExecutionStatus.RUNNING:
                raise ExecutionReliabilityDenied("execution_not_running")
            execution = await self.repository._owned_execution(
                user_id,
                workspace_id,
                execution_id,
            )
            released_id = await self.session.scalar(
                update(ControlledAgentExecution)
                .where(
                    ControlledAgentExecution.id == execution_id,
                    ControlledAgentExecution.user_id == user_id,
                    ControlledAgentExecution.workspace_id == workspace_id,
                    ControlledAgentExecution.completed_at.is_(None),
                    ControlledAgentExecution.lease_owner_id == owner_id,
                    ControlledAgentExecution.lease_generation == generation,
                    ControlledAgentExecution.lease_expires_at > released_at,
                )
                .values(
                    lease_owner_id=None,
                    lease_acquired_at=None,
                    lease_expires_at=None,
                )
                .returning(ControlledAgentExecution.id)
                .execution_options(synchronize_session=False)
            )
            if released_id is None:
                raise ExecutionReliabilityDenied("lease_not_current")
            await self.session.refresh(execution)
            await self._record_event(
                trace_id=trace_id,
                execution=execution,
                event_type="execution.lease_released",
                recorded_at=released_at,
                metadata={
                    "attemptCount": execution.attempt_count,
                    "leaseGeneration": execution.lease_generation,
                },
            )
        return ExecutionLeaseChange(
            execution_id=execution_id,
            generation=execution.lease_generation,
            expires_at=None,
            attempt_count=execution.attempt_count,
            trace_id=trace_id,
        )

    async def recover_expired_lease(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        expected_generation: int,
        recovered_at: datetime,
    ) -> ExecutionRecovery:
        """Fence one abandoned owner and make its execution retry-eligible."""

        recovered_at = _aware_utc(recovered_at)
        if expected_generation < 1:
            raise ExecutionReliabilityDenied("lease_identity_invalid")
        trace_id = uuid.uuid4()
        async with self.session.begin_nested():
            await self._validate_claim_authority(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                evaluated_at=recovered_at,
            )
            current = await self.repository.current_state(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
            )
            if current is None or ExecutionStatus(current.status) is not ExecutionStatus.RUNNING:
                raise ExecutionReliabilityDenied("execution_not_recoverable")
            execution = await self.repository._owned_execution(
                user_id,
                workspace_id,
                execution_id,
            )
            if await self._has_authoritative_effect(execution_id):
                raise ExecutionReliabilityDenied("authoritative_result_exists")
            if execution.lease_expires_at is None:
                raise ExecutionReliabilityDenied("execution_lease_missing")
            if _aware_utc(execution.lease_expires_at) > recovered_at:
                raise ExecutionReliabilityDenied("execution_lease_active")
            if _aware_utc(execution.deadline_at) <= recovered_at:
                raise ExecutionReliabilityDenied("execution_deadline_expired")
            if execution.attempt_count >= execution.max_attempts:
                raise ExecutionReliabilityDenied("execution_attempts_exhausted")
            next_retry_at = recovered_at + retry_delay(execution.attempt_count)
            if next_retry_at >= _aware_utc(execution.deadline_at):
                raise ExecutionReliabilityDenied("execution_retry_window_exhausted")
            recovered_id = await self.session.scalar(
                update(ControlledAgentExecution)
                .where(
                    ControlledAgentExecution.id == execution_id,
                    ControlledAgentExecution.user_id == user_id,
                    ControlledAgentExecution.workspace_id == workspace_id,
                    ControlledAgentExecution.completed_at.is_(None),
                    ControlledAgentExecution.lease_generation == expected_generation,
                    ControlledAgentExecution.lease_owner_id.is_not(None),
                    ControlledAgentExecution.lease_expires_at <= recovered_at,
                    ControlledAgentExecution.deadline_at > next_retry_at,
                    ControlledAgentExecution.attempt_count < ControlledAgentExecution.max_attempts,
                )
                .values(
                    lease_owner_id=None,
                    lease_acquired_at=None,
                    lease_expires_at=None,
                    lease_generation=ControlledAgentExecution.lease_generation + 1,
                    next_retry_at=next_retry_at,
                )
                .returning(ControlledAgentExecution.id)
                .execution_options(synchronize_session=False)
            )
            if recovered_id is None:
                raise ExecutionReliabilityDenied("execution_recovery_conflict")
            await self.session.refresh(execution)
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=execution_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    status=ExecutionStatus.READY,
                    recorded_at=recovered_at,
                    safe_reason_code="lease_expired",
                )
            )
            await self._record_event(
                trace_id=trace_id,
                execution=execution,
                event_type="execution.lease_recovered",
                recorded_at=recovered_at,
                metadata={
                    "attemptCount": execution.attempt_count,
                    "supersededGeneration": expected_generation,
                    "leaseGeneration": execution.lease_generation,
                    "nextRetryAt": next_retry_at.isoformat(),
                },
            )
        return ExecutionRecovery(
            execution_id=execution_id,
            superseded_generation=expected_generation,
            generation=execution.lease_generation,
            next_retry_at=next_retry_at,
            attempt_count=execution.attempt_count,
            trace_id=trace_id,
        )

    async def execute_retry(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        attempted_at: datetime,
        action: Callable[[ExecutionLease], Awaitable[object]],
    ) -> RetryExecutionResult:
        """Claim and execute one eligible retry in an atomic server transaction."""

        attempted_at = _aware_utc(attempted_at)
        existing = await self._terminal_duplicate(
            user_id=user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
        )
        if existing is not None:
            return existing

        trace_id = uuid.uuid4()
        async with self.session.begin_nested():
            lease = await self.claim(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                claimed_at=attempted_at,
            )
            failure: RetryFailureClassification | None = None
            try:
                async with self.session.begin_nested():
                    await action(lease)
            except RetryActionError as exc:
                failure = exc.classification
            except Exception:
                failure = RetryFailureClassification.ACTION_INVALID

            execution = await self.repository._owned_execution(
                user_id,
                workspace_id,
                execution_id,
            )
            await self._assert_current_lease(
                execution=execution,
                lease=lease,
                evaluated_at=attempted_at,
            )
            if failure is None:
                await self.repository.append_state(
                    ExecutionStateRecord(
                        state_id=uuid.uuid4(),
                        execution_id=execution_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        status=ExecutionStatus.SUCCEEDED,
                        recorded_at=attempted_at,
                    )
                )
                await self.session.refresh(execution)
                await self._record_event(
                    trace_id=trace_id,
                    execution=execution,
                    event_type="execution.retry_succeeded",
                    recorded_at=attempted_at,
                    metadata={
                        "attemptCount": execution.attempt_count,
                        "leaseGeneration": lease.generation,
                    },
                )
                return RetryExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.SUCCEEDED,
                    attempt_count=execution.attempt_count,
                    failure_classification=None,
                    next_retry_at=None,
                    duplicate=False,
                    trace_id=trace_id,
                )
            return await self._record_retry_failure(
                execution=execution,
                lease=lease,
                classification=failure,
                failed_at=attempted_at,
                trace_id=trace_id,
            )

    async def _record_retry_failure(
        self,
        *,
        execution: ControlledAgentExecution,
        lease: ExecutionLease,
        classification: RetryFailureClassification,
        failed_at: datetime,
        trace_id: uuid.UUID,
    ) -> RetryExecutionResult:
        retryable = classification in RETRYABLE_FAILURES
        exhausted = execution.attempt_count >= execution.max_attempts
        next_retry_at = failed_at + retry_delay(execution.attempt_count)
        deadline_exhausted = next_retry_at >= _aware_utc(execution.deadline_at)
        if not retryable or exhausted or deadline_exhausted:
            safe_reason = (
                "execution_attempts_exhausted"
                if retryable and exhausted
                else "execution_retry_window_exhausted"
                if retryable and deadline_exhausted
                else classification.value
            )
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=execution.id,
                    user_id=execution.user_id,
                    workspace_id=execution.workspace_id,
                    status=ExecutionStatus.FAILED,
                    recorded_at=failed_at,
                    safe_reason_code=safe_reason,
                )
            )
            await self.session.refresh(execution)
            await self._record_event(
                trace_id=trace_id,
                execution=execution,
                event_type="execution.retry_failed",
                recorded_at=failed_at,
                metadata={
                    "attemptCount": execution.attempt_count,
                    "failureClassification": safe_reason,
                    "leaseGeneration": lease.generation,
                },
            )
            return RetryExecutionResult(
                execution_id=execution.id,
                status=ExecutionStatus.FAILED,
                attempt_count=execution.attempt_count,
                failure_classification=safe_reason,
                next_retry_at=None,
                duplicate=False,
                trace_id=trace_id,
            )

        updated_id = await self.session.scalar(
            update(ControlledAgentExecution)
            .where(
                ControlledAgentExecution.id == execution.id,
                ControlledAgentExecution.lease_owner_id == lease.owner_id,
                ControlledAgentExecution.lease_generation == lease.generation,
                ControlledAgentExecution.completed_at.is_(None),
            )
            .values(
                lease_owner_id=None,
                lease_acquired_at=None,
                lease_expires_at=None,
                lease_generation=ControlledAgentExecution.lease_generation + 1,
                next_retry_at=next_retry_at,
            )
            .returning(ControlledAgentExecution.id)
            .execution_options(synchronize_session=False)
        )
        if updated_id is None:
            raise ExecutionReliabilityDenied("lease_not_current")
        await self.session.refresh(execution)
        await self.repository.append_state(
            ExecutionStateRecord(
                state_id=uuid.uuid4(),
                execution_id=execution.id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                status=ExecutionStatus.READY,
                recorded_at=failed_at,
                safe_reason_code=classification.value,
            )
        )
        await self._record_event(
            trace_id=trace_id,
            execution=execution,
            event_type="execution.retry_scheduled",
            recorded_at=failed_at,
            metadata={
                "attemptCount": execution.attempt_count,
                "failureClassification": classification.value,
                "leaseGeneration": execution.lease_generation,
                "nextRetryAt": next_retry_at.isoformat(),
            },
        )
        return RetryExecutionResult(
            execution_id=execution.id,
            status=ExecutionStatus.READY,
            attempt_count=execution.attempt_count,
            failure_classification=classification.value,
            next_retry_at=next_retry_at,
            duplicate=False,
            trace_id=trace_id,
        )

    async def _assert_current_lease(
        self,
        *,
        execution: ControlledAgentExecution,
        lease: ExecutionLease,
        evaluated_at: datetime,
    ) -> None:
        current_id = await self.session.scalar(
            update(ControlledAgentExecution)
            .where(
                ControlledAgentExecution.id == execution.id,
                ControlledAgentExecution.completed_at.is_(None),
                ControlledAgentExecution.lease_owner_id == lease.owner_id,
                ControlledAgentExecution.lease_generation == lease.generation,
                ControlledAgentExecution.lease_expires_at > evaluated_at,
            )
            .values(lease_expires_at=ControlledAgentExecution.lease_expires_at)
            .returning(ControlledAgentExecution.id)
            .execution_options(synchronize_session=False)
        )
        if current_id is None:
            raise ExecutionReliabilityDenied("lease_not_current")

    async def _has_authoritative_effect(self, execution_id: uuid.UUID) -> bool:
        return (
            await self.session.scalar(
                select(ControlledAgentReversibleWriteEffect.effect_id).where(
                    ControlledAgentReversibleWriteEffect.execution_id == execution_id
                )
            )
            is not None
        )

    async def _terminal_duplicate(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> RetryExecutionResult | None:
        execution = await self.repository._owned_execution(user_id, workspace_id, execution_id)
        current = await self.repository.current_state(
            user_id=user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
        )
        if current is not None and ExecutionStatus(current.status) is ExecutionStatus.SUCCEEDED:
            return RetryExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.SUCCEEDED,
                attempt_count=execution.attempt_count,
                failure_classification=None,
                next_retry_at=None,
                duplicate=True,
                trace_id=uuid.UUID(int=0),
            )
        return None

    async def _validate_claim_authority(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        evaluated_at: datetime,
    ) -> None:
        try:
            inspection = await self.repository.inspect_execution(
                user_id=user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                limit=100,
                offset=0,
            )
        except AgentPersistenceNotFound as exc:
            raise ExecutionReliabilityDenied("authority_not_found") from exc
        execution = inspection.execution
        grant_row = next(
            (row for row in inspection.grants if row.grant_id == execution.grant_id),
            None,
        )
        if grant_row is None:
            raise ExecutionReliabilityDenied("authority_not_found")
        grant = self.repository._load_contract(
            CapabilityGrant,
            grant_row.payload,
            grant_row.payload_digest,
        )
        if (
            grant.user_id != user_id
            or grant.workspace_id != workspace_id
            or grant.execution_id != execution_id
            or grant.context_digest != execution.context_digest
            or grant.plan_digest != execution.plan_digest
        ):
            raise ExecutionReliabilityDenied("authority_binding_mismatch")
        if evaluated_at < grant.issued_at or evaluated_at >= grant.expires_at:
            raise ExecutionReliabilityDenied("grant_inactive")
        revoked_ids = {
            row.grant_id
            for row in inspection.revocations
            if _aware_utc(row.revoked_at) <= evaluated_at
        }
        if grant.grant_id in revoked_ids:
            raise ExecutionReliabilityDenied("grant_revoked")
        if not grant.approval_required:
            return
        approval_row = next(
            (row for row in inspection.approvals if row.approval_id == grant.approval_id),
            None,
        )
        if approval_row is None:
            raise ExecutionReliabilityDenied("approval_missing")
        approval = self.repository._load_contract(
            ApprovalRecord,
            approval_row.payload,
            approval_row.payload_digest,
        )
        if (
            approval.decision is not ApprovalDecision.APPROVED
            or approval.grant_id != grant.grant_id
            or approval.user_id != user_id
            or approval.workspace_id != workspace_id
            or approval.execution_id != execution_id
            or approval.context_digest != grant.context_digest
            or approval.plan_digest != grant.plan_digest
        ):
            raise ExecutionReliabilityDenied("approval_binding_mismatch")
        if evaluated_at < approval.decided_at or evaluated_at >= approval.expires_at:
            raise ExecutionReliabilityDenied("approval_inactive")

    async def _claim_denial_reason(
        self,
        execution_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        claimed_at: datetime,
    ) -> str:
        execution = await self.repository._owned_execution(user_id, workspace_id, execution_id)
        if execution.completed_at is not None or execution.terminal_outcome is not None:
            return "execution_terminal"
        if _aware_utc(execution.deadline_at) <= claimed_at:
            return "execution_deadline_expired"
        if execution.attempt_count >= execution.max_attempts:
            return "execution_attempts_exhausted"
        if execution.next_retry_at is not None and _aware_utc(execution.next_retry_at) > claimed_at:
            return "execution_retry_not_eligible"
        if (
            execution.lease_owner_id is not None
            and execution.lease_expires_at is not None
            and _aware_utc(execution.lease_expires_at) > claimed_at
        ):
            return "execution_lease_active"
        return "execution_claim_conflict"

    async def _record_event(
        self,
        *,
        trace_id: uuid.UUID,
        execution: ControlledAgentExecution,
        event_type: str,
        recorded_at: datetime,
        metadata: dict[str, str | int],
    ) -> None:
        attributes = tuple(
            AuditAttribute(key=key, value=value) for key, value in sorted(metadata.items())
        )
        await self.repository.append_audit_event(
            AuditEvent(
                event_id=uuid.uuid4(),
                trace_id=trace_id,
                execution_id=execution.id,
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                event_type=event_type,
                recorded_at=recorded_at,
                attributes=attributes,
            )
        )
        trace_metadata: dict[str, JsonValue] = dict(metadata)
        await self.trace_service.record_event(
            RecordTraceEventInput(
                trace_id=trace_id,
                event_type=event_type,
                actor_type="service",
                user_id=execution.user_id,
                workspace_id=execution.workspace_id,
                object_id=execution.id,
                object_type="controlled_agent_execution",
                operation=event_type,
                status="succeeded",
                metadata=trace_metadata,
            )
        )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def retry_delay(attempt_count: int) -> timedelta:
    """Return deterministic bounded exponential delay for the completed attempt."""

    exponent = max(attempt_count - 1, 0)
    seconds = min(
        RETRY_BASE_DELAY.total_seconds() * (2**exponent),
        RETRY_MAX_DELAY.total_seconds(),
    )
    return timedelta(seconds=seconds)


__all__ = [
    "EXECUTION_LEASE_DURATION",
    "RETRYABLE_FAILURES",
    "RETRY_BASE_DELAY",
    "RETRY_MAX_DELAY",
    "ControlledExecutionReliability",
    "ExecutionLease",
    "ExecutionLeaseChange",
    "ExecutionRecovery",
    "ExecutionReliabilityDenied",
    "RetryActionError",
    "RetryExecutionResult",
    "RetryFailureClassification",
    "retry_delay",
]
