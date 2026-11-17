from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from opencanvas_api.db.models import (
    DomainActivityEntry,
    DomainEventDeliveryAttempt,
    DomainEventOutbox,
)
from opencanvas_api.services.domain_events import (
    DomainEventOutboxService,
    OutboxClaim,
    OutboxOwnershipError,
)
from opencanvas_api.services.outbox_dispatcher import DurableActivityConsumer


@pytest.fixture
async def locked_claim_database():
    path = os.environ.get("M78_CAPACITY_LOCAL_PG_FILE")
    if not path:
        pytest.skip("requires separately owned disposable local PostgreSQL")
    retained = json.loads(await asyncio.to_thread(Path(path).read_text, encoding="utf-8-sig"))
    assert "127.0.0.1" in retained["url"]
    admin = create_async_engine(retained["url"])
    schema = "outbox_expiry_" + uuid.uuid4().hex
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        retained["url"], connect_args={"server_settings": {"search_path": schema}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    current = datetime.now(UTC)
    outbox_id, event_id = uuid.uuid4(), uuid.uuid4()
    claim = OutboxClaim(
        outbox_id, event_id, "focused-holder", 1, 1, current + timedelta(seconds=30)
    )
    # This test isolates actual PostgreSQL fencing. The exact production table
    # columns/checks are retained; unrelated cross-table fixtures are not seeded.
    async with engine.begin() as connection:
        for model in (DomainEventOutbox, DomainEventDeliveryAttempt, DomainActivityEntry):
            await connection.execute(
                CreateTable(model.__table__, include_foreign_key_constraints=[])
            )
    async with sessions() as session:
        session.add(
            DomainEventOutbox(
                outbox_id=outbox_id,
                event_id=event_id,
                user_id=uuid.uuid4(),
                workspace_id=uuid.uuid4(),
                delivery_state="delivering",
                eligible_at=current,
                attempt_count=1,
                max_attempts=3,
                lease_owner_id=claim.owner_id,
                lease_generation=1,
                lease_acquired_at=current,
                lease_expires_at=claim.lease_expires_at,
            )
        )
        await session.commit()
    try:
        yield SimpleNamespace(engine=engine, sessions=sessions), claim, current
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.parametrize("operation", ["consumer", "complete", "fail"])
async def test_expiry_is_sampled_after_actual_row_lock_wait(locked_claim_database, operation):
    db, claim, original_time = locked_claim_database
    clock = [original_time]
    async with db.sessions() as blocker:
        await blocker.scalar(
            select(DomainEventOutbox)
            .where(DomainEventOutbox.outbox_id == claim.outbox_id)
            .with_for_update()
        )
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))

        async def waiting_operation():
            if operation == "consumer":
                await DurableActivityConsumer(db.sessions, clock=lambda: clock[0]).deliver(claim)
                return
            async with db.sessions() as session:
                service = DomainEventOutboxService(session, clock=lambda: clock[0])
                if operation == "complete":
                    await service.complete(claim)
                else:
                    await service.fail(
                        claim, failure_classification="consumer_retryable", retryable=True
                    )
                await session.commit()

        pending = asyncio.create_task(waiting_operation())
        try:
            for _ in range(100):
                async with db.sessions() as observer:
                    blocked = await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE :holder=ANY(pg_blocking_pids(pid))"
                        ),
                        {"holder": blocker_pid},
                    )
                    await observer.rollback()
                if blocked:
                    break
                await asyncio.sleep(0.01)
            assert blocked == 1 and not pending.done()
            clock[0] = claim.lease_expires_at + timedelta(seconds=1)
            await blocker.rollback()
            with pytest.raises(OutboxOwnershipError):
                await asyncio.wait_for(pending, timeout=5)
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with db.sessions() as session:
        row = await session.get(DomainEventOutbox, claim.outbox_id)
        assert row.delivery_state == "delivering" and row.attempt_count == 1
        assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(DomainEventDeliveryAttempt)) == 0
        )


async def test_clock_injection_and_explicit_fixture_time_remain_supported(locked_claim_database):
    db, claim, original_time = locked_claim_database
    async with db.sessions() as session:
        await DomainEventOutboxService(session, clock=lambda: original_time).validate_claim(claim)
        await session.rollback()
        service = DomainEventOutboxService(
            session, clock=lambda: claim.lease_expires_at + timedelta(seconds=1)
        )
        with pytest.raises(OutboxOwnershipError):
            await service.validate_claim(claim)
        await session.rollback()
        await service.validate_claim(claim, now=original_time)
        await session.rollback()


async def test_projection_crossing_expiry_rolls_back_before_ack(locked_claim_database, monkeypatch):
    db, claim, original_time = locked_claim_database
    clock = [original_time]

    async def projection_crosses_deadline(service, owned):
        row = await service.session.get(DomainEventOutbox, owned.outbox_id)
        service.session.add(
            DomainActivityEntry(
                activity_id=uuid.uuid4(),
                event_id=owned.event_id,
                user_id=row.user_id,
                workspace_id=row.workspace_id,
                canvas_id=None,
                sequence=1,
                event_type="canonical.resource.created",
                subject_kind="canonical_resource",
                subject_id=uuid.uuid4(),
                actor_user_id=row.user_id,
                trace_id=uuid.uuid4(),
                projection_version="activity-v1",
                occurred_at=original_time,
            )
        )
        await service.session.flush()
        clock[0] = owned.lease_expires_at + timedelta(seconds=1)
        return True

    monkeypatch.setattr(DomainEventOutboxService, "project_activity", projection_crosses_deadline)
    with pytest.raises(OutboxOwnershipError):
        await DurableActivityConsumer(db.sessions, clock=lambda: clock[0]).deliver(claim)
    async with db.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 0
