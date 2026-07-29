from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    CollaborationAuditEvent,
    DurableJobAttempt,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.durable_jobs import DurableJobService, JobLease
from tests.postgres_support import disposable_postgres_database
from tests.test_durable_jobs import _principal, _source

pytestmark = pytest.mark.postgres


async def _seed_system_authority(database: Database) -> None:
    now = datetime.now(UTC)
    membership_id = uuid.uuid5(SYSTEM_WORKSPACE_ID, "owner-membership")
    trace_id = uuid.uuid5(membership_id, "bootstrap-trace")
    audit_id = uuid.uuid5(membership_id, "bootstrap-audit")
    async with database.sessions() as session:
        session.add(
            Workspace(
                id=SYSTEM_WORKSPACE_ID,
                owner_id=SYSTEM_USER_ID,
                name="Test workspace",
            )
        )
        await session.flush()
        session.add(
            WorkspaceAuthorityVersion(
                workspace_id=SYSTEM_WORKSPACE_ID,
                authority_generation=1,
                last_trace_id=trace_id,
                updated_at=now,
            )
        )
        session.add(
            CollaborationAuditEvent(
                audit_event_id=audit_id,
                workspace_id=SYSTEM_WORKSPACE_ID,
                actor_user_id=SYSTEM_USER_ID,
                subject_kind="workspace_membership",
                subject_id=membership_id,
                action="membership.test_bootstrap",
                outcome="succeeded",
                reason_code="test_owner_bootstrap",
                metadata_digest=hashlib.sha256(b"test-owner-bootstrap").hexdigest(),
                trace_id=trace_id,
                recorded_at=now,
            )
        )
        session.add(
            WorkspaceMembership(
                membership_id=membership_id,
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                created_by_user_id=SYSTEM_USER_ID,
                accepted_invitation_id=None,
                collaboration_policy_version="collaboration-policy-v1",
                creation_trace_id=trace_id,
                creation_audit_event_id=audit_id,
                created_at=now,
            )
        )
        session.add(
            WorkspaceMembershipTransition(
                transition_id=uuid.uuid5(membership_id, "bootstrap-transition"),
                membership_id=membership_id,
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                sequence=0,
                previous_state=None,
                current_state="active",
                previous_role=None,
                current_role="owner",
                reason_code="test_owner_bootstrap",
                collaboration_policy_version="collaboration-policy-v1",
                authority_generation=1,
                actor_user_id=SYSTEM_USER_ID,
                trace_id=trace_id,
                audit_event_id=audit_id,
                recorded_at=now,
            )
        )
        await session.commit()


@pytest.fixture
def postgres_durable_database_url() -> Iterator[str]:
    yield from disposable_postgres_database()


@pytest.mark.asyncio
async def test_postgresql_skip_locked_claims_once_and_evidence_is_append_only(
    postgres_durable_database_url: str,
) -> None:
    database = Database(postgres_durable_database_url)
    now = datetime.now(UTC)
    try:
        await _seed_system_authority(database)
        canvas_id, document_id, version_id = await _source(database)
        async with database.sessions() as session:
            job = await DurableJobService(session, lease_seconds=30).create_document_job(
                principal=_principal(),
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                document_id=document_id,
                document_version_id=version_id,
                idempotency_key="postgres-skip-locked",
                deadline_at=now + timedelta(minutes=5),
                now=now,
            )
            job_id = job.id
            await session.commit()

        first_claimed = asyncio.Event()
        release_first = asyncio.Event()

        async def first_worker() -> JobLease | None:
            async with database.sessions() as session:
                lease = await DurableJobService(session, lease_seconds=30).claim_one(
                    worker_id="postgres-worker-one",
                    now=now + timedelta(seconds=1),
                )
                first_claimed.set()
                await release_first.wait()
                await session.commit()
                return lease

        async def second_worker() -> JobLease | None:
            await first_claimed.wait()
            async with database.sessions() as session:
                lease = await DurableJobService(session, lease_seconds=30).claim_one(
                    worker_id="postgres-worker-two",
                    now=now + timedelta(seconds=1),
                )
                release_first.set()
                await session.commit()
                return lease

        first, second = await asyncio.gather(first_worker(), second_worker())
        assert first is not None
        assert second is None
        assert first.job_run_id == job_id

        async with database.sessions() as session:
            attempt = await session.scalar(
                select(DurableJobAttempt).where(DurableJobAttempt.job_run_id == job_id)
            )
            assert attempt is not None
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    update(DurableJobAttempt)
                    .where(DurableJobAttempt.attempt_id == attempt.attempt_id)
                    .values(outcome="succeeded")
                )
            await session.rollback()
    finally:
        await database.dispose()
