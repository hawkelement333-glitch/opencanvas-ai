from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from opencanvas_api.core.config import Settings
from opencanvas_api.db.session import Database, MeasuredAsyncQueuePool
from opencanvas_api.services.documents.errors import DocumentStorageError
from opencanvas_api.services.documents.storage import LocalVersionedObjectStorage
from opencanvas_api.services.observability import InMemoryTelemetrySink, build_observability
from opencanvas_api.services.operational_observations import (
    after_commit_metric,
    bind_operational_telemetry,
    current_telemetry,
    emit_document_boundary,
    observe_workspace_state,
    record_provider_observation,
)


def observer():
    sink = InMemoryTelemetrySink()
    settings = Settings(
        app_mode="test",
        telemetry_enabled=True,
        telemetry_exporter="memory",
        telemetry_pseudonymization_secret="p" * 48,
        telemetry_sample_ratio=1,
        telemetry_buffer_size=1024,
        telemetry_batch_size=512,
    )
    return build_observability(settings, sink=sink), sink


def metrics(sink, name):
    return [s.payload["value"] for s in sink.signals if s.name == name]


async def test_storage_measures_actual_bytes_operations_and_failure_without_content(tmp_path):
    telemetry, sink = observer()
    storage = LocalVersionedObjectStorage(tmp_path)
    content = b"private document: secret@example.invalid"
    with bind_operational_telemetry(telemetry):
        stored = await storage.put_immutable(
            security_class="quarantine",
            object_id=uuid.uuid4(),
            object_version_id=uuid.uuid4(),
            content=content,
            expected_sha256=hashlib.sha256(content).hexdigest(),
        )
        assert (
            await storage.read_version(
                physical_key=stored.physical_key, provider_version_id=stored.provider_version_id
            )
            == content
        )
        await storage.delete_version(
            physical_key=stored.physical_key, provider_version_id=stored.provider_version_id
        )
        with pytest.raises(DocumentStorageError):
            await storage.read_version(
                physical_key=stored.physical_key, provider_version_id=stored.provider_version_id
            )
    assert current_telemetry() is None
    await telemetry.flush()
    assert sum(metrics(sink, "mobius.storage.operations")) == 4
    assert sum(metrics(sink, "mobius.storage.failures")) == 1
    assert len(metrics(sink, "mobius.storage.duration")) == 4
    serialized = json.dumps([s.as_dict() for s in sink.signals])
    assert content.decode() not in serialized and stored.physical_key not in serialized
    assert telemetry.counters.rejected == 0
    await telemetry.close()


async def test_durable_metrics_and_transaction_outcomes_follow_commit_not_flush():
    telemetry, sink = observer()
    database = Database("sqlite+aiosqlite:///:memory:")
    with bind_operational_telemetry(telemetry):
        async with database.sessions() as session:
            await session.execute(text("SELECT 1"))
            after_commit_metric(session, "mobius.scanner.throughput", 1, "scanner")
            await session.flush()
            await telemetry.flush()
            assert not metrics(sink, "mobius.scanner.throughput")
            await session.rollback()
        async with database.sessions() as session:
            await session.execute(text("SELECT 1"))
            after_commit_metric(session, "mobius.scanner.throughput", 1, "scanner")
            await session.commit()
    await telemetry.flush()
    assert metrics(sink, "mobius.scanner.throughput") == [1]
    assert len(metrics(sink, "mobius.database.transactions")) == 2
    await database.dispose()
    await telemetry.close()


async def test_real_pool_contention_records_timeout_and_elapsed_acquisition(tmp_path):
    telemetry, sink = observer()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}",
        poolclass=MeasuredAsyncQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.03,
    )
    with bind_operational_telemetry(telemetry):
        async with engine.connect():
            with pytest.raises(PoolTimeoutError):
                async with engine.connect():
                    raise AssertionError("exhausted pool must not admit")
    await telemetry.flush()
    assert metrics(sink, "mobius.database.timeouts") == [1]
    assert len(metrics(sink, "mobius.database.pool.acquire")) == 2
    assert max(metrics(sink, "mobius.database.pool.acquire")) >= 25
    await engine.dispose()
    await telemetry.close()


def provider(kind, now):
    resource = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/fixture"
    if kind == "backup":
        resource += "/providers/Microsoft.DBforPostgreSQL/flexibleServers/fixture"
        body = {
            "value": [
                {
                    "id": resource + "/backups/actual-completion",
                    "properties": {"completedTime": (now - timedelta(hours=2)).isoformat()},
                }
            ]
        }
        request = {"method": "GET", "resourceId": resource + "/backups", "apiVersion": "2025-08-01"}
    else:
        body = {
            "properties": {
                "nextLink": None,
                "columns": [
                    {"name": n} for n in ("PreTaxCost", "UsageDate", "CostStatus", "Currency")
                ],
                "rows": [[2.5, 20261116, "Forecast", "USD"], [1.5, 20261117, "Forecast", "USD"]],
            }
        }
        request = {
            "method": "POST",
            "resourceId": resource + "/providers/Microsoft.CostManagement/forecast",
            "apiVersion": "2025-03-01",
            "body": {
                "type": "Usage",
                "timeframe": "Custom",
                "includeActualCost": False,
                "includeFreshPartialCost": False,
                "timePeriod": {"from": "2026-11-16T00:00:00Z", "to": "2026-11-17T23:59:59Z"},
                "dataset": {
                    "granularity": "Daily",
                    "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
                },
            },
        }
    native = {"request": request, "response": {"status": 200, "body": body}}
    return {
        "schema": "mobius-provider-observation-v1",
        "resourceId": resource,
        "release": "release",
        "deployment": "deployment",
        "kind": kind,
        "observedAt": now.isoformat(),
        "native": native,
        "nativeSha256": hashlib.sha256(
            json.dumps(native, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


@pytest.mark.parametrize(
    "kind,name,value",
    [("backup", "mobius.backup.freshness", 7200), ("cost", "mobius.cost.estimated", 4)],
)
async def test_provider_values_derive_from_bound_native_fields(kind, name, value):
    telemetry, sink = observer()
    now = datetime.now(UTC)
    record = provider(kind, now)
    with bind_operational_telemetry(telemetry):
        assert (
            record_provider_observation(
                record,
                expected_resource_ids=frozenset({record["resourceId"]}),
                expected_release="release",
                expected_deployment="deployment",
                now=now,
            )
            == name
        )
    await telemetry.flush()
    assert metrics(sink, name) == [value]
    assert record["resourceId"] not in json.dumps([s.as_dict() for s in sink.signals])
    await telemetry.close()


@pytest.mark.parametrize("mutation", ["scope", "hash", "stale", "failed", "empty", "currency"])
async def test_missing_or_untrusted_provider_records_never_emit_healthy_zero(mutation):
    telemetry, sink = observer()
    now = datetime.now(UTC)
    record = provider("cost", now)
    expected = frozenset({record["resourceId"]})
    if mutation == "scope":
        record["resourceId"] += "-other"
    elif mutation == "hash":
        record["nativeSha256"] = "0" * 64
    elif mutation == "stale":
        record["observedAt"] = (now - timedelta(minutes=6)).isoformat()
    elif mutation == "failed":
        record["native"]["response"]["status"] = 403
    elif mutation == "empty":
        record["native"]["response"]["body"]["properties"]["rows"] = []
    else:
        record["native"]["response"]["body"]["properties"]["rows"][0][3] = "EUR"
    if mutation not in {"hash", "scope", "stale"}:
        record["nativeSha256"] = hashlib.sha256(
            json.dumps(record["native"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    with bind_operational_telemetry(telemetry), pytest.raises(ValueError):
        record_provider_observation(
            record,
            expected_resource_ids=expected,
            expected_release="release",
            expected_deployment="deployment",
            now=now,
        )
    await telemetry.flush()
    assert not sink.signals
    await telemetry.close()


@pytest.mark.parametrize(
    "mutation",
    ["missing-body", "monthly", "actual", "partial", "aggregation", "date", "duplicate", "naive"],
)
async def test_forecast_requires_bound_request_and_daily_dates(mutation):
    telemetry, sink = observer()
    now = datetime.now(UTC)
    record = provider("cost", now)
    request = record["native"]["request"]
    forecast = request["body"]
    rows = record["native"]["response"]["body"]["properties"]["rows"]
    if mutation == "missing-body":
        request.pop("body")
    elif mutation == "monthly":
        forecast["timeframe"] = "MonthToDate"
    elif mutation == "actual":
        forecast["includeActualCost"] = True
    elif mutation == "partial":
        forecast["includeFreshPartialCost"] = True
    elif mutation == "aggregation":
        forecast["dataset"]["aggregation"]["totalCost"]["function"] = "Average"
    elif mutation == "date":
        rows[0][1] = 20261115
    elif mutation == "duplicate":
        rows.append(rows[0])
    else:
        forecast["timePeriod"]["from"] = "2026-11-16T00:00:00"
    record["nativeSha256"] = hashlib.sha256(
        json.dumps(record["native"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with bind_operational_telemetry(telemetry), pytest.raises(ValueError):
        record_provider_observation(
            record,
            expected_resource_ids=frozenset({record["resourceId"]}),
            expected_release="release",
            expected_deployment="deployment",
            now=now,
        )
    await telemetry.flush()
    assert not sink.signals
    await telemetry.close()


async def test_real_scoped_integrity_queries_and_index_age_keep_absence_unknown():
    telemetry, sink = observer()
    database = Database("sqlite+aiosqlite:///:memory:")
    workspace = uuid.uuid4()
    now = datetime.now(UTC)
    async with database.engine.begin() as connection:
        for sql in [
            "CREATE TABLE domain_events(event_id UUID, workspace_id UUID, user_id UUID)",
            "CREATE TABLE domain_event_outbox(event_id UUID, workspace_id UUID, user_id UUID)",
            "CREATE TABLE domain_activity_entries(event_id UUID, workspace_id UUID, user_id UUID)",
            "CREATE TABLE retrieval_heads(publication_id UUID, "
            "workspace_id UUID, activation_kind TEXT)",
            "CREATE TABLE index_publications(publication_id UUID, "
            "workspace_id UUID, published_at DATETIME)",
        ]:
            await connection.execute(text(sql))
        await connection.execute(
            text("INSERT INTO domain_event_outbox VALUES(:event,:workspace,:user)"),
            {"event": uuid.uuid4().hex, "workspace": workspace.hex, "user": uuid.uuid4().hex},
        )
    with bind_operational_telemetry(telemetry):
        async with database.sessions() as session:
            result = await observe_workspace_state(session, workspace, now=now)
    await telemetry.flush()
    assert result == {"indexFreshnessSeconds": None, "referenceIntegrityFindings": 1}
    assert metrics(sink, "mobius.evidence.integrity") == [1]
    assert not metrics(sink, "mobius.indexer.freshness")
    await database.dispose()
    await telemetry.close()


async def test_document_link_is_real_identity_bound_and_preserves_http_context():
    telemetry, sink = observer()
    document, workspace = uuid.uuid4(), uuid.uuid4()
    with bind_operational_telemetry(telemetry):
        http = telemetry.start_span("http.server.request", component="api")
        emit_document_boundary(document, workspace)
        http.end(outcome="success")
        worker = telemetry.start_span(
            "worker.execution",
            component="worker",
            links=(telemetry.span_link("document", document, scope=(workspace,)),),
        )
        worker.end(outcome="success")
    await telemetry.flush()
    api = next(s for s in sink.signals if s.name == "domain_event.publish")
    http_signal = next(s for s in sink.signals if s.name == "http.server.request")
    worker_signal = next(s for s in sink.signals if s.name == "worker.execution")
    assert api.payload["trace_id"] == http_signal.payload["trace_id"]
    assert api.payload["links"] == worker_signal.payload["links"]
    assert str(document) not in json.dumps([s.as_dict() for s in sink.signals])
    await telemetry.close()


async def test_scan_replay_emits_one_durable_verdict(database, tmp_path):
    from tests.test_object_ingestion import test_clean_verdict_promotes_exact_bytes_once

    telemetry, sink = observer()
    with bind_operational_telemetry(telemetry):
        await test_clean_verdict_promotes_exact_bytes_once(database, tmp_path)
    await telemetry.flush()
    assert metrics(sink, "mobius.scanner.throughput") == [1]
    assert len(metrics(sink, "mobius.scanner.duration")) == 1
    assert not metrics(sink, "mobius.scanner.quarantine")
    assert telemetry.counters.rejected == 0
    await telemetry.close()


async def test_actual_index_drift_emits_failure_without_published_throughput(
    app,
    client,
    api_prefix,
    database,
    tmp_path,
    monkeypatch,
):
    from tests.test_indexer import test_component_drift_and_source_change_block_publication

    telemetry, sink = observer()
    monkeypatch.setattr(app.state, "observability", telemetry)
    with bind_operational_telemetry(telemetry):
        await test_component_drift_and_source_change_block_publication(
            client,
            api_prefix,
            database,
            tmp_path,
            monkeypatch,
        )
    await telemetry.flush()
    assert metrics(sink, "mobius.indexer.drift") == [1]
    assert not metrics(sink, "mobius.indexer.throughput")
    assert len(metrics(sink, "mobius.indexer.stage_duration")) == 3
    await telemetry.close()


async def test_actual_index_publication_replay_counts_committed_effects_only(
    app,
    client,
    api_prefix,
    database,
    monkeypatch,
):
    from tests.test_indexer import test_native_index_request_publishes_once_and_replay_is_read_only

    telemetry, sink = observer()
    monkeypatch.setattr(app.state, "observability", telemetry)
    await test_native_index_request_publishes_once_and_replay_is_read_only(
        client,
        api_prefix,
        database,
    )
    await telemetry.flush()
    assert metrics(sink, "mobius.indexer.throughput") == [1, 1]
    await telemetry.close()


async def test_provider_observer_validation_cannot_claim_export(tmp_path, monkeypatch):
    import argparse

    from scripts.operational_observer import observe

    for key, value in {
        "OPENCANVAS_APP_MODE": "test",
        "OPENCANVAS_TELEMETRY_ENABLED": "true",
        "OPENCANVAS_TELEMETRY_EXPORTER": "memory",
        "OPENCANVAS_TELEMETRY_RELEASE": "release",
        "OPENCANVAS_TELEMETRY_DEPLOYMENT": "deployment",
        "OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET": "p" * 48,
    }.items():
        monkeypatch.setenv(key, value)
    record = provider("backup", datetime.now(UTC))
    readback = tmp_path / "readback.json"
    binding = tmp_path / "binding.json"
    readback.write_text(json.dumps(record), encoding="utf-8")
    binding.write_text(
        json.dumps(
            {
                "resourceIds": [record["resourceId"]],
                "release": "release",
                "deployment": "deployment",
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        readback=readback,
        bindings=binding,
        emit=False,
        readback_sha256=hashlib.sha256(readback.read_bytes()).hexdigest(),
        bindings_sha256=hashlib.sha256(binding.read_bytes()).hexdigest(),
    )
    result = await observe(args)
    assert result["exported"] is False and result["managedAcceptance"] == "unproved"
    args.emit = True
    with pytest.raises(ValueError, match="HTTP telemetry"):
        await observe(args)


async def test_integrity_observer_reads_real_evidence_and_detects_changed_baseline(
    database, tmp_path
):
    from opencanvas_api.services.evidence_observer import observe_evidence_integrity
    from tests.test_object_ingestion import _completed_upload

    _, _, workspace, _, _ = await _completed_upload(database, tmp_path)
    telemetry, sink = observer()
    with bind_operational_telemetry(telemetry):
        async with database.sessions() as session:
            first = await observe_evidence_integrity(session, workspace)
            assert first["unknown"] == ["append_only_mutations"]
            second = await observe_evidence_integrity(session, workspace, previous=first)
            assert not second["unknown"]
            assert sum(second["findings"].values()) == 0
            # Local disposable corruption fixture only: monitor itself has no write path.
            await session.execute(
                text(
                    "UPDATE object_ingestion_audit_events "
                    "SET reason_code='fixture_corruption' WHERE workspace_id=:workspace"
                ),
                {"workspace": workspace.hex},
            )
            changed = await observe_evidence_integrity(session, workspace, previous=first)
            assert changed["findings"]["append_only_mutations"] > 0
            assert changed["repairPerformed"] is False
            await session.rollback()
    await telemetry.flush()
    values = metrics(sink, "mobius.evidence.integrity")
    assert values[0] == 0 and values[-1] > 0 and len(values) == 2
    assert str(workspace) not in json.dumps([s.as_dict() for s in sink.signals])
    await telemetry.close()


def test_integrity_classifies_existing_categories_without_repair_or_unknown_zero():
    from opencanvas_api.services.evidence_observer import TABLES, assess_evidence_rows

    workspace, event_id, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    rows = {name: [] for name in TABLES}
    rows["domain_events"] = [
        {
            "event_id": event_id,
            "workspace_id": workspace,
            "user_id": user,
            "sequence": 2,
            "scope_id": workspace,
            "event_type": "upload.requested",
            "source_identity": "fixture",
            "trace_id": uuid.uuid4(),
            "audit_event_id": uuid.uuid4(),
        }
    ]
    # Same event delivered twice, plus a separate orphan, all beyond the existing 300-second age.
    rows["domain_event_outbox"] = [
        {
            "workspace_id": workspace,
            "event_id": identity,
            "delivery_state": "pending",
            "created_at": now - timedelta(seconds=301),
        }
        for identity in [event_id, event_id, uuid.uuid4()]
    ]
    rows["trace_events"] = [
        {
            "workspace_id": workspace,
            "event_id": uuid.uuid4(),
            "trace_id": uuid.uuid4(),
            "parent_trace_id": uuid.uuid4(),
        }
    ]
    rows["upload_session_transitions"] = [
        {
            "workspace_id": workspace,
            "transition_id": uuid.uuid4(),
            "session_id": uuid.uuid4(),
            "sequence": 1,
            "previous_state": "invented",
            "current_state": "requested",
        }
    ]
    first = assess_evidence_rows(rows, workspace, previous=None, now=now, telemetry_gaps=1)
    assert first["unknown"] == ["append_only_mutations"]
    for category in [
        "audit_sequence_gaps",
        "trace_parent_gaps",
        "event_outbox_orphans",
        "evidence_link_orphans",
        "impossible_transitions",
        "stale_backlog",
        "duplicate_durable_identities",
        "telemetry_gaps",
    ]:
        assert first["findings"][category] > 0
    rows["domain_events"][0]["source_identity"] = "changed"
    second = assess_evidence_rows(rows, workspace, previous=first, now=now, telemetry_gaps=0)
    assert second["findings"]["append_only_mutations"] == 1
    assert second["repairPerformed"] is False and second["investigationClosure"] == "not-authorized"
    with pytest.raises(ValueError, match="inventory"):
        assess_evidence_rows({}, workspace, previous=None, now=now, telemetry_gaps=None)
