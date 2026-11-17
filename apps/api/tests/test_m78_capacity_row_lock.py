from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from infra.milestone_7_8.capacity_fixtures import prepare_row_lock_stage
from infra.milestone_7_8.capacity_validation import admit_row_lock, prepare, scoped_row_lock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from opencanvas_api.core.config import Settings


def package():
    capacity = prepare(
        Settings(database_pool_size=5, database_max_overflow=0).model_dump(),
        request_budget=10000,
        concurrency_cap=8,
    )
    stage, operations = prepare_row_lock_stage(capacity, hold_seconds=3)
    fixture = {
        "canvasId": str(uuid.uuid4()),
        "workspaceId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
    }
    return stage, operations, fixture


def test_row_lock_scope_time_and_pressure_guard():
    stage, operations, fixture = package()
    assert len(operations) == 16 and stage["proofRole"] == "api"
    deadline = datetime.now(UTC) + timedelta(minutes=3)
    assert admit_row_lock(stage, fixture, deadline)["canvasId"] == uuid.UUID(fixture["canvasId"])
    stage["rowLock"]["target"]["ownerId"] = str(uuid.uuid4())
    with pytest.raises(ValueError, match="accepted core scope"):
        admit_row_lock(stage, fixture, deadline)
    stage, _, fixture = package()
    stage["rowLock"]["holdSeconds"] = 601
    with pytest.raises(ValueError, match="outside approved bound"):
        admit_row_lock(stage, fixture, deadline)
    stage, _, fixture = package()
    with pytest.raises(ValueError, match="insufficient authority"):
        admit_row_lock(stage, fixture, datetime.now(UTC) + timedelta(seconds=20))
    capacity = prepare(
        Settings(database_pool_size=5, database_max_overflow=0).model_dump(),
        request_budget=10000,
        concurrency_cap=4,
    )
    with pytest.raises(ValueError, match="exceed actual API pool"):
        prepare_row_lock_stage(capacity, hold_seconds=120)


@pytest.fixture
async def postgres_scope():
    path = os.environ.get("M78_CAPACITY_LOCAL_PG_FILE")
    if not path:
        pytest.skip("requires separately owned disposable local PostgreSQL")
    retained = json.loads(await asyncio.to_thread(Path(path).read_text, encoding="utf-8-sig"))
    assert "127.0.0.1" in retained["url"]
    admin = create_async_engine(retained["url"])
    schema = "capacity_rowlock_" + uuid.uuid4().hex
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        retained["url"], connect_args={"server_settings": {"search_path": schema}}
    )
    db = SimpleNamespace(engine=engine, sessions=async_sessionmaker(engine, expire_on_commit=False))
    stage, _, fixture = package()
    binding = admit_row_lock(stage, fixture, datetime.now(UTC) + timedelta(minutes=3))
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE workspaces(id uuid PRIMARY KEY, owner_id uuid NOT NULL, "
                "deleted_at timestamptz, lifecycle_state text NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE canvases(id uuid PRIMARY KEY, "
                "workspace_id uuid REFERENCES workspaces(id), revision integer NOT NULL DEFAULT 0)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO workspaces(id,owner_id,lifecycle_state) "
                "VALUES(:workspaceId,:ownerId,'active')"
            ),
            binding,
        )
        await connection.execute(
            text("INSERT INTO canvases(id,workspace_id) VALUES(:canvasId,:workspaceId)"), binding
        )
    try:
        yield db, binding
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_actual_postgres_write_blocks_until_bounded_rollback(postgres_scope):
    db, binding = postgres_scope
    events = []
    journal = SimpleNamespace(step=lambda name, value: events.append((name, value)))

    async def write():
        async with db.sessions() as session:
            await session.execute(
                text("UPDATE canvases SET revision=revision+1 WHERE id=:canvasId"), binding
            )
            await session.commit()

    from opencanvas_api.services.operational_observations import bind_operational_telemetry
    from tests.test_operational_observations import metrics, observer

    telemetry, sink = observer()
    try:
        with bind_operational_telemetry(telemetry):
            async with scoped_row_lock(db, binding, journal) as receipt:
                pending = asyncio.create_task(write())
                await asyncio.sleep(0.2)
                assert not pending.done()
                await asyncio.wait_for(pending, timeout=8)
        await telemetry.flush()
        waits = metrics(sink, "mobius.database.lock_wait")
        assert waits and all(value > 0 for value in waits)
        observed = [row["ownRoleDatabasePendingLockWaitMs"] for row in receipt["waitObservations"]]
        assert all(value in observed for value in waits)
    finally:
        await telemetry.close()
    assert receipt["rollbackVerified"] and receipt["holderTransactionLocksAfter"] == 0
    assert any(row["blocked"] == 1 for row in receipt["waitObservations"])
    assert 2.8 <= receipt["actualHoldSeconds"] < 8
    assert [name for name, _ in events] == [
        "capacity-row-lock-acquired",
        "capacity-row-lock-released",
    ]


async def test_wrong_owner_denied_and_exception_releases_actual_lock(postgres_scope):
    db, binding = postgres_scope
    journal = SimpleNamespace(step=lambda *args: None)
    with pytest.raises(ValueError, match="owned synthetic canvas"):
        async with scoped_row_lock(db, {**binding, "ownerId": uuid.uuid4()}, journal):
            pytest.fail("wrong owner acquired lock")
    with pytest.raises(RuntimeError, match="focused abort"):
        async with scoped_row_lock(db, binding, journal) as receipt:
            raise RuntimeError("focused abort")
    assert receipt["rollbackVerified"]
    async with db.sessions() as session:
        assert (
            await session.scalar(
                text("SELECT id FROM canvases WHERE id=:canvasId FOR UPDATE NOWAIT"), binding
            )
            == binding["canvasId"]
        )
        await session.rollback()
