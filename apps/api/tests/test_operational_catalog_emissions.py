from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from opencanvas_api.db.models import SYSTEM_WORKSPACE_ID
from opencanvas_api.main import ApiRequestAdmission
from opencanvas_api.services.operational_observations import (
    bind_operational_telemetry,
    observe_database_lock_wait,
    observe_index_coverage,
)
from tests.test_operational_observations import metrics, observer


async def test_queue_cancellation_counts_commits_once_and_omits_rollback(database):
    from opencanvas_api.services.durable_jobs import DurableJobService
    from tests.test_durable_jobs import _create, _principal

    now = datetime.now(UTC)
    job = await _create(database, now=now)
    telemetry, sink = observer()
    with bind_operational_telemetry(telemetry):
        async with database.sessions() as session:
            await DurableJobService(session).cancel(
                principal=_principal(),
                workspace_id=SYSTEM_WORKSPACE_ID,
                job_run_id=job,
                reason_code="local_validation",
                now=now,
            )
            await session.rollback()
        await telemetry.flush()
        assert not metrics(sink, "mobius.queue.cancellations")
        async with database.sessions() as session:
            service = DurableJobService(session)
            for _ in range(2):
                await service.cancel(
                    principal=_principal(),
                    workspace_id=SYSTEM_WORKSPACE_ID,
                    job_run_id=job,
                    reason_code="local_validation",
                    now=now,
                )
            await session.commit()
    await telemetry.flush()
    assert metrics(sink, "mobius.queue.cancellations") == [1]
    await telemetry.close()


@pytest.mark.parametrize("scenario", ["recovery", "retry", "replay"])
async def test_actual_queue_transitions_export_new_catalog_measurements(database, scenario):
    from tests import test_durable_jobs

    telemetry, sink = observer()
    function = {
        "recovery": test_durable_jobs.test_bounded_retry_succeeds_once_and_stale_worker_is_fenced,
        "retry": test_durable_jobs.test_transient_retry_is_bounded_and_succeeds_once,
        "replay": (
            test_durable_jobs.test_dead_letter_replay_requires_current_authority_and_new_identity
        ),
    }[scenario]
    with bind_operational_telemetry(telemetry):
        await function(database)
    await telemetry.flush()
    assert all(value > 0 for value in metrics(sink, "mobius.queue.claim_duration"))
    assert len(metrics(sink, "mobius.queue.claim_duration")) == (1 if scenario == "replay" else 2)
    for name in {
        "recovery": ["lease_loss", "retries", "stale_suppression"],
        "retry": ["retries"],
        "replay": ["dead_letters", "replays"],
    }[scenario]:
        assert metrics(sink, "mobius.queue." + name) == [1]
    assert telemetry.counters.rejected == 0
    await telemetry.close()


@pytest.mark.parametrize("scenario", ["deduplication", "cancellation", "publication_fence"])
async def test_actual_indexer_catalog_events(
    app, client, api_prefix, database, tmp_path, monkeypatch, scenario
):
    from tests import test_indexer
    from tests.test_full_closure_recovery import (
        test_stale_restored_result_cannot_replace_real_publication as stale_check,
    )

    telemetry, sink = observer()
    monkeypatch.setattr(app.state, "observability", telemetry)
    with bind_operational_telemetry(telemetry):
        if scenario == "deduplication":
            await test_indexer.test_native_index_request_publishes_once_and_replay_is_read_only(
                client, api_prefix, database
            )
        elif scenario == "cancellation":
            await test_indexer.test_cancel_and_conflicting_idempotency_fail_closed(
                client, api_prefix, database
            )
        else:
            await stale_check(app, client, api_prefix, database, tmp_path)
    await telemetry.flush()
    name, expected = {
        "deduplication": ("deduplication", [1, 1]),
        "cancellation": ("cancellations", [1]),
        "publication_fence": ("publication_conflict", [1]),
    }[scenario]
    assert metrics(sink, "mobius.indexer." + name) == expected
    assert telemetry.counters.rejected == 0
    await telemetry.close()


async def test_clean_source_coverage_uses_actual_current_policy_rows(database, tmp_path):
    from sqlalchemy import select

    from opencanvas_api.db.models import StorageObjectVersion
    from opencanvas_api.services.documents import MemoryDocumentStorage, MockEmbeddingProvider
    from opencanvas_api.services.indexer import IngestionService
    from opencanvas_api.services.object_ingestion import (
        MalwareScanService,
        scanner_result_signature,
    )
    from tests.test_object_ingestion import (
        _bind_result,
        _completed_upload,
        _principal,
        _scan_result,
    )

    settings, storage, workspace, canvas, completed = await _completed_upload(database, tmp_path)
    telemetry, sink = observer()
    with bind_operational_telemetry(telemetry):
        async with database.sessions() as session:
            initial = await observe_index_coverage(
                session, workspace, settings, now=datetime.now(UTC)
            )
            assert initial == {"cleanSources": 0, "indexedCleanSources": 0, "indexCoverage": None}
        result = await _bind_result(database, completed, _scan_result(completed))
        async with database.sessions() as session:
            await MalwareScanService(session, settings=settings, storage=storage).record_result(
                result=result,
                signature=scanner_result_signature(result, settings.scanner_result_secret),
            )
            await session.commit()
        async with database.sessions() as session:
            clean = await observe_index_coverage(
                session, workspace, settings, now=datetime.now(UTC)
            )
            assert clean == {"cleanSources": 1, "indexedCleanSources": 0, "indexCoverage": 0.0}
            expired = await observe_index_coverage(
                session,
                workspace,
                settings,
                now=datetime.now(UTC)
                + timedelta(seconds=settings.malware_scan_result_max_age_seconds + 1),
            )
            assert expired["indexCoverage"] is None
        async with database.sessions() as session:
            version = await session.scalar(
                select(StorageObjectVersion).where(
                    StorageObjectVersion.workspace_id == workspace,
                    StorageObjectVersion.security_class == "clean",
                )
            )
            content = await storage.read_version(
                physical_key=version.physical_key, provider_version_id=version.provider_version_id
            )
            source_storage = MemoryDocumentStorage(_objects={version.physical_key: content})
            service = IngestionService(
                session, settings=settings, storage=source_storage, provider=MockEmbeddingProvider()
            )
            view = await service.request(
                principal=_principal(),
                workspace_id=workspace,
                canvas_id=canvas,
                document_id=completed.session.document_id,
                document_version=1,
                idempotency_key="coverage-native-publication",
            )
            revision = await service.build(view.request.request_id)
            await service.publish(view.request.request_id, revision.revision_id)
            await session.commit()
        async with database.sessions() as session:
            published = await observe_index_coverage(
                session, workspace, settings, now=datetime.now(UTC)
            )
            assert published == {"cleanSources": 1, "indexedCleanSources": 1, "indexCoverage": 1.0}
    await telemetry.flush()
    assert metrics(sink, "mobius.indexer.coverage") == [0.0, 1.0]
    await telemetry.close()


async def test_limiter_records_actual_saturation_and_rejected_bypass_attempts():
    from opencanvas_api.services.rate_limits import InMemoryAtomicRateLimitStore, RateLimitDimension
    from tests.test_shared_rate_limits import _service

    service = _service(InMemoryAtomicRateLimitStore())
    dimensions = [RateLimitDimension(kind="workspace", subject="private-workspace", limit=1)]
    telemetry, sink = observer()
    with bind_operational_telemetry(telemetry):
        assert (await service.consume(operation="upload", dimensions=dimensions)).allowed
        assert not (await service.consume(operation="upload", dimensions=dimensions)).allowed
        for dims, cost in ((dimensions, 0), ([], 1)):
            with pytest.raises(ValueError):
                await service.consume(operation="upload", dimensions=dims, cost=cost)
    await telemetry.flush()
    assert metrics(sink, "mobius.limiter.saturation") == [1]
    assert metrics(sink, "mobius.limiter.bypass") == [1, 1]
    assert service.metrics.decisions == 2 and telemetry.counters.rejected == 0
    await telemetry.close()


def asgi_scope(telemetry):
    return {
        "type": "http",
        "path": "/api/v1/work",
        "app": SimpleNamespace(state=SimpleNamespace(observability=telemetry)),
    }


async def test_api_admission_measures_two_slots_denies_without_business_call():
    telemetry, sink = observer()
    release, both_started = asyncio.Event(), asyncio.Event()
    calls = 0

    async def app(scope, receive, send):
        nonlocal calls
        calls += 1
        if calls == 2:
            both_started.set()
        await release.wait()

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.disconnect"}

    admission = ApiRequestAdmission(app, limit=2, api_prefix="/api/v1")
    tasks = [asyncio.create_task(admission(asgi_scope(telemetry), receive, send)) for _ in range(2)]
    await asyncio.wait_for(both_started.wait(), 2)
    await admission(asgi_scope(telemetry), receive, send)
    assert calls == 2 and admission.active == 2
    assert sent[0]["status"] == 503 and (b"retry-after", b"1") in sent[0]["headers"]
    release.set()
    await asyncio.gather(*tasks)
    await telemetry.flush()
    assert admission.active == 0 and metrics(sink, "mobius.api.saturation") == [
        0.5,
        1.0,
        1.0,
        0.5,
        0.0,
    ]
    await telemetry.close()


@pytest.mark.parametrize("cancel", [False, True])
async def test_api_slot_releases_after_error_or_cancellation(cancel):
    telemetry, sink = observer()
    started = asyncio.Event()

    async def app(scope, receive, send):
        started.set()
        if cancel:
            await asyncio.Event().wait()
        raise RuntimeError("local failure")

    async def no_io(*args):
        return None

    admission = ApiRequestAdmission(app, limit=1, api_prefix="/api/v1")
    task = asyncio.create_task(admission(asgi_scope(telemetry), no_io, no_io))
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await task
    await telemetry.flush()
    assert admission.active == 0 and metrics(sink, "mobius.api.saturation") == [1.0, 0.0]
    await telemetry.close()


async def test_unconfigured_api_budget_emits_no_invented_ratio():
    telemetry, sink = observer()

    async def no_io(*args):
        return None

    await ApiRequestAdmission(no_io, limit=None, api_prefix="/api/v1")(
        asgi_scope(telemetry), no_io, no_io
    )
    await telemetry.flush()
    assert not metrics(sink, "mobius.api.saturation")
    await telemetry.close()


async def test_api_capacity_response_keeps_security_headers_and_liveness(monkeypatch):
    from opencanvas_api import main
    from opencanvas_api.core.config import Settings

    monkeypatch.setattr(
        main, "get_settings", lambda: Settings(app_mode="test", api_request_concurrency_limit=1)
    )
    app = main.create_app()
    started, release = asyncio.Event(), asyncio.Event()

    @app.get("/api/v1/held-local-check")
    async def held():
        started.set()
        await release.wait()
        return {"done": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        task = asyncio.create_task(client.get("/api/v1/held-local-check"))
        await asyncio.wait_for(started.wait(), 2)
        origin = Settings().cors_origins[0]
        rejected = await client.get("/api/v1/held-local-check", headers={"Origin": origin})
        assert rejected.status_code == 503 and rejected.headers["retry-after"] == "1"
        assert rejected.headers["x-content-type-options"] == "nosniff"
        assert rejected.headers["access-control-allow-origin"] == origin
        assert (
            "traceparent" in rejected.headers
            and Settings().correlation_header_name in rejected.headers
        )
        assert (await client.get("/api/v1/health/live")).status_code == 200
        release.set()
        assert (await task).status_code == 200
    await app.state.observability.close()
    await app.state.shared_rate_limiter.close()


@pytest.mark.skipif(
    not os.environ.get("M78_LOCAL_LOCK_TEST_URL"),
    reason="explicit disposable local PostgreSQL required",
)
async def test_postgres_pending_lock_reports_native_waitstart_only():
    engine = create_async_engine(os.environ["M78_LOCAL_LOCK_TEST_URL"])
    telemetry, sink = observer()
    lock = uuid.uuid4().int % (2**62)
    try:
        async with engine.connect() as holder, engine.connect() as blocked:
            await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
            waiter = asyncio.create_task(
                blocked.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
            )
            try:
                with bind_operational_telemetry(telemetry):
                    async with AsyncSession(engine) as session:
                        observed = None
                        for _ in range(100):
                            observed = await observe_database_lock_wait(session)
                            if observed is not None and observed > 0:
                                break
                            await asyncio.sleep(0.02)
                        assert observed is not None and observed > 0
            finally:
                await holder.rollback()
                await asyncio.wait_for(waiter, 5)
                await blocked.rollback()
        await telemetry.flush()
        assert metrics(sink, "mobius.database.lock_wait")[-1] > 0
        assert telemetry.counters.rejected == 0
    finally:
        await engine.dispose()
        await telemetry.close()
