from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infra.milestone_7_8.queue_grant_intervention import intervene, snapshot
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture
async def scoped_postgres():
    private = Path(
        ".runtime/milestone_7_8/full-closure-local/destination/local-postgres.private.json"
    )
    if not await asyncio.to_thread(private.is_file):
        pytest.skip("owned focused PostgreSQL fixture is not running")
    document = json.loads(await asyncio.to_thread(private.read_text))
    source = make_url(document["url"]).set(drivername="postgresql+asyncpg")
    admin = create_async_engine(source, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    suffix = uuid.uuid4().hex[:10]
    owner, worker = "m78_queue_owner_" + suffix, "m78_queue_worker_" + suffix
    async with admin.connect() as connection:
        assert not await connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='opencanvas')")
        )
        await connection.execute(text(f'CREATE ROLE "{owner}" NOLOGIN'))
        await connection.execute(text(f'CREATE ROLE "{worker}" NOLOGIN'))
        await connection.execute(text(f'CREATE DATABASE opencanvas OWNER "{owner}"'))
    engines = []
    for role in (owner, worker):
        engine = create_async_engine(source.set(database="opencanvas"), poolclass=NullPool)

        def configure_role(connection, record, bound_role=role):
            cursor = connection.cursor()
            cursor.execute(f'SET ROLE "{bound_role}"')
            cursor.close()

        event.listen(engine.sync_engine, "connect", configure_role)
        engines.append(engine)
    owner_engine, worker_engine = engines
    workspace = str(uuid.uuid4())
    try:
        async with owner_engine.begin() as connection:
            await connection.execute(text("CREATE TABLE public.workspaces(id uuid PRIMARY KEY)"))
            await connection.execute(
                text(
                    "CREATE TABLE public.document_processing_jobs(id uuid PRIMARY KEY, "
                    "workspace_id uuid NOT NULL, status text NOT NULL)"
                )
            )
            await connection.execute(
                text("INSERT INTO public.workspaces VALUES(:workspace)"),
                {"workspace": uuid.UUID(workspace)},
            )
            await connection.execute(
                text(
                    "INSERT INTO public.document_processing_jobs VALUES(:job,:workspace,'queued')"
                ),
                {"job": uuid.uuid4(), "workspace": uuid.UUID(workspace)},
            )
            await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{worker}"'))
        yield owner_engine, worker_engine, owner, worker, workspace
    finally:
        for engine in engines:
            await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text("DROP DATABASE opencanvas WITH (FORCE)"))
            await connection.execute(text(f'DROP ROLE "{worker}"'))
            await connection.execute(text(f'DROP ROLE "{owner}"'))
        await admin.dispose()


@pytest.mark.parametrize("grantable", [False, True])
async def test_real_worker_denial_and_exact_select_restoration(scoped_postgres, grantable):
    owner_engine, worker_engine, owner, worker, workspace = scoped_postgres
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                f'GRANT SELECT ON public.document_processing_jobs TO "{worker}"'
                + (" WITH GRANT OPTION" if grantable else "")
            )
        )
    denied = asyncio.Event()
    captures = {}

    def capture(name, value):
        captures[name] = value
        if name == "queue-grant-denied":
            denied.set()

    task = asyncio.create_task(
        intervene(
            owner_engine,
            migration=owner,
            worker=worker,
            workspace=workspace,
            hold_seconds=0.5,
            deadline=datetime.now(UTC) + timedelta(seconds=60),
            capture=capture,
        )
    )
    await asyncio.wait_for(denied.wait(), timeout=5)
    async with worker_engine.connect() as connection:
        with pytest.raises(DBAPIError) as failure:
            await connection.execute(text("SELECT * FROM public.document_processing_jobs"))
        assert failure.value.orig.sqlstate == "42501"
    result = await task
    assert result["capturedSelectRestored"] and result["aclRestored"]
    assert result["scopedExistingJobsUnchanged"]
    assert result["beforeAclSha256"] == result["afterAclSha256"]
    async with worker_engine.connect() as connection:
        assert (
            await connection.scalar(text("SELECT count(*) FROM public.document_processing_jobs"))
            == 1
        )


async def test_restoration_runs_after_callback_failure(scoped_postgres):
    owner_engine, _, owner, worker, workspace = scoped_postgres
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f'GRANT SELECT ON public.document_processing_jobs TO "{worker}"')
        )

    def capture(name, value):
        if name == "queue-grant-denied":
            raise RuntimeError("controlled-local-observation-failure")

    with pytest.raises(RuntimeError, match="controlled-local"):
        await intervene(
            owner_engine,
            migration=owner,
            worker=worker,
            workspace=workspace,
            hold_seconds=0.1,
            deadline=datetime.now(UTC) + timedelta(seconds=60),
            capture=capture,
        )
    async with owner_engine.connect() as connection:
        result = await snapshot(connection, migration=owner, worker=worker, workspace=workspace)
    assert result["effectiveSelect"]


async def test_wrong_owner_or_workspace_cannot_start_fault(scoped_postgres):
    owner_engine, _, owner, worker, workspace = scoped_postgres
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f'GRANT SELECT ON public.document_processing_jobs TO "{worker}"')
        )
        for bad_owner, bad_workspace in ((worker, workspace), (owner, str(uuid.uuid4()))):
            with pytest.raises(ValueError):
                await snapshot(
                    connection, migration=bad_owner, worker=worker, workspace=bad_workspace
                )
        assert (await snapshot(connection, migration=owner, worker=worker, workspace=workspace))[
            "effectiveSelect"
        ]
