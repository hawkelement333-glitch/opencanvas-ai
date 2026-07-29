from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opencanvas_api.core.config import Settings
from opencanvas_api.services.ai import MockAIProvider, ObservedAIProvider
from opencanvas_api.services.context import ContextBundle
from opencanvas_api.services.observability import (
    METRIC_CATALOG,
    AlertEvaluator,
    AlertRule,
    AlertState,
    InMemoryTelemetrySink,
    IntegritySnapshot,
    OperationalHealth,
    OperationalTelemetry,
    Severity,
    SignalKind,
    assess_integrity,
    build_observability,
    parse_traceparent,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OBSERVABILITY_DOCS = REPOSITORY_ROOT / "docs" / "observability"


def _settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "app_mode": "test",
        "telemetry_enabled": True,
        "telemetry_exporter": "memory",
        "telemetry_pseudonymization_secret": "t" * 48,
        "telemetry_sample_ratio": 1.0,
        "telemetry_batch_size": 16,
        "telemetry_buffer_size": 32,
        "telemetry_cardinality_budget": 8,
    }
    values.update(updates)
    return Settings(**values)


def _telemetry(
    *,
    sink: InMemoryTelemetrySink | None = None,
    **settings: object,
) -> tuple[OperationalTelemetry, InMemoryTelemetrySink]:
    selected_sink = sink or InMemoryTelemetrySink()
    return build_observability(_settings(**settings), sink=selected_sink), selected_sink


async def test_closed_log_schema_redacts_and_rejects_private_fields() -> None:
    telemetry, sink = _telemetry()
    accepted = telemetry.emit_log(
        event_name="api.request.completed",
        severity=Severity.INFO,
        component="api",
        fields={
            "operation": "read\nrequest",
            "route": "/workspaces/{workspace_id}/documents/{document_id}",
            "method": "GET",
            "status_code": 200,
            "status_class": "2xx",
            "outcome": "success",
            "duration_ms": 7,
            "correlation_kind": "request",
            "correlation": telemetry.correlate("request", "raw-request"),
        },
    )
    rejected = telemetry.emit_log(
        event_name="api.request.completed",
        severity=Severity.INFO,
        component="api",
        fields={"prompt": "private prompt"},
    )
    assert accepted is True
    assert rejected is False
    assert await telemetry.flush() is True
    assert len(sink.signals) == 1
    record = sink.signals[0]
    assert record.kind is SignalKind.APPLICATION_LOG
    serialized = json.dumps(record.as_dict())
    assert "read\\nrequest" not in serialized
    assert "private prompt" not in serialized
    assert "raw-request" not in serialized


@pytest.mark.parametrize(
    "value",
    [
        "person@example.test",
        "192.0.2.10",
        "Bearer eyJaaaaaaaaaaaa.bbbbbbbbbbbb.cccccccccccc",
        "password=never-log-this",
        "https://storage.invalid/blob?sig=secret",
    ],
)
async def test_redaction_covers_credentials_identifiers_and_signed_queries(value: str) -> None:
    telemetry, sink = _telemetry()
    assert telemetry.emit_log(
        event_name="security.control.triggered",
        severity=Severity.WARNING,
        component="api",
        fields={
            "operation": value,
            "outcome": "denied",
            "correlation_kind": "request",
            "correlation": telemetry.correlate("request", "request"),
        },
        security=True,
    )
    await telemetry.flush()
    serialized = json.dumps(sink.signals[0].as_dict())
    assert value not in serialized


def test_pseudonymous_correlations_are_scope_and_environment_isolated() -> None:
    first, _ = _telemetry()
    second, _ = _telemetry(telemetry_deployment="another")
    value = "00000000-0000-4000-8000-000000000001"
    a = first.correlate("job", value, scope=("workspace-a", "canvas-a"))
    b = first.correlate("job", value, scope=("workspace-b", "canvas-a"))
    c = second.correlate("job", value, scope=("workspace-a", "canvas-a"))
    assert len({a, b, c}) == 3
    assert value not in {a, b, c}


def test_metric_schema_unknown_labels_and_cardinality_budget_fail_closed() -> None:
    telemetry, _ = _telemetry()
    assert telemetry.record_metric(
        "mobius.api.requests",
        1,
        labels={"method": "GET", "outcome": "success"},
    )
    assert telemetry.record_metric(
        "mobius.api.requests",
        1,
        labels={"method": "TRACE", "outcome": "success"},
    )
    assert not telemetry.record_metric(
        "mobius.api.requests",
        1,
        labels={"workspace": "private", "outcome": "success"},
    )
    assert not telemetry.record_metric("unknown.metric", 1, labels={})
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        telemetry.record_metric(
            "mobius.api.requests",
            1,
            labels={"method": method, "outcome": "server_error"},
        )
    assert not telemetry.record_metric(
        "mobius.api.requests",
        1,
        labels={"method": "HEAD", "outcome": "client_error"},
    )
    assert telemetry.counters.rejected >= 3


async def test_w3c_span_links_limits_and_product_trace_separation() -> None:
    telemetry, sink = _telemetry(telemetry_max_span_events=1)
    parent = parse_traceparent("00-0123456789abcdef0123456789abcdef-0123456789abcdef-01")
    assert parent is not None
    link = telemetry.span_link("job", "job-1", scope=("workspace-1",))
    span = telemetry.start_span(
        "worker.execution",
        component="worker",
        parent=parent,
        links=(link,),
        attributes={
            "operation": "document_processing",
            "component": "worker",
            "correlation": telemetry.correlate("worker", "worker-1"),
        },
    )
    span.add_event("lease.renewed", {"outcome": "success"})
    span.add_event("lease.renewed", {"outcome": "success"})
    span.end(outcome="success")
    await telemetry.flush()
    record = sink.signals[0]
    assert record.kind is SignalKind.SPAN
    assert record.payload["trace_id"] == parent.trace_id
    assert len(record.payload["events"]) == 1  # type: ignore[arg-type]
    serialized = json.dumps(record.as_dict())
    assert "product_trace" not in serialized
    assert "prompt" not in serialized


def test_baggage_is_bounded_and_rejects_private_or_unknown_fields() -> None:
    telemetry, _ = _telemetry(telemetry_baggage_allowlist=["operation", "component"])
    assert telemetry.safe_baggage(
        {
            "operation": "document_processing",
            "component": "worker",
            "prompt": "private prompt",
            "unknown": "not approved",
        }
    ) == {
        "operation": "document_processing",
        "component": "worker",
    }


async def test_sink_failure_backpressure_and_shutdown_are_bounded() -> None:
    sink = InMemoryTelemetrySink(fail=True)
    telemetry, _ = _telemetry(
        sink=sink,
        telemetry_buffer_size=16,
        telemetry_batch_size=8,
        telemetry_retry_limit=1,
        telemetry_health_failure_threshold=1,
    )
    business_committed = True
    for index in range(20):
        telemetry.emit_log(
            event_name="durable_job.transition",
            severity=Severity.INFO,
            component="queue",
            fields={
                "operation": "complete",
                "outcome": "success",
                "count": index,
                "correlation_kind": "job",
                "correlation": telemetry.correlate("job", index),
            },
        )
    assert business_committed is True
    assert telemetry.buffered == 16
    assert telemetry.counters.dropped == 4
    assert await telemetry.flush() is False
    assert telemetry.health() is OperationalHealth.UNAVAILABLE
    assert await telemetry.close() is False
    assert telemetry.buffered == 0


async def test_export_timeout_does_not_raise_into_business_flow() -> None:
    sink = InMemoryTelemetrySink(delay_seconds=0.2)
    telemetry, _ = _telemetry(
        sink=sink,
        telemetry_export_timeout_seconds=0.05,
        telemetry_retry_limit=0,
        telemetry_shutdown_timeout_seconds=0.1,
    )
    telemetry.record_metric(
        "mobius.api.requests",
        1,
        labels={"method": "GET", "outcome": "success"},
    )
    result = await telemetry.flush()
    assert result is False
    assert telemetry.counters.export_timeouts == 1
    await telemetry.close()


async def test_provider_instrumentation_never_exports_prompt_context_or_response() -> None:
    telemetry, sink = _telemetry()
    provider = ObservedAIProvider(MockAIProvider(), telemetry)
    context = ContextBundle(
        node_ids=[],
        snapshot=[{"title": "private title", "text": "private source text"}],
        rendered="private source text",
    )
    result = await provider.generate("private prompt", context)
    assert result.text
    await telemetry.flush()
    serialized = json.dumps([signal.as_dict() for signal in sink.signals])
    assert "private prompt" not in serialized
    assert "private source text" not in serialized
    assert "private title" not in serialized
    assert "Mock AI response" not in serialized
    assert "provider.call" in serialized


def test_alert_firing_recovery_missing_data_and_deduplication() -> None:
    evaluator = AlertEvaluator()
    rule = AlertRule(
        alert_id="queue-backlog-v1",
        threshold=300,
        recovery_threshold=120,
        firing_windows=2,
        recovery_windows=2,
        missing_data="breach",
    )
    state = AlertState()
    state = evaluator.evaluate(rule, state, 350)
    assert state.firing is False
    state = evaluator.evaluate(rule, state, 360)
    assert state.firing is True and state.notifications == 1
    state = evaluator.evaluate(rule, state, 400)
    assert state.notifications == 1
    state = evaluator.evaluate(rule, state, 100)
    state = evaluator.evaluate(rule, state, 100)
    assert state.firing is False and state.notifications == 2
    missing = evaluator.evaluate(rule, AlertState(), None)
    assert missing.breach_windows == 1


def test_integrity_monitor_reports_without_repairing_evidence() -> None:
    snapshot = IntegritySnapshot(
        audit_sequence_gaps=1,
        stale_backlog=3,
        duplicate_durable_identities=2,
    )
    findings = assess_integrity(snapshot)
    assert [(item.classification, item.severity, item.count) for item in findings] == [
        ("audit_sequence_gaps", "critical", 1),
        ("stale_backlog", "warning", 3),
        ("duplicate_durable_identities", "critical", 2),
    ]
    assert snapshot.audit_sequence_gaps == 1


def test_runtime_configuration_rejects_silent_or_unsafe_exporters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="explicit bounded exporter"):
        Settings(app_mode="test", telemetry_enabled=True)
    with pytest.raises(ValidationError, match="requires telemetry enablement"):
        Settings(app_mode="test", telemetry_exporter="memory")
    with pytest.raises(ValidationError, match="requires an endpoint"):
        Settings(
            app_mode="test",
            telemetry_enabled=True,
            telemetry_exporter="http",
            telemetry_pseudonymization_secret="t" * 48,
        )
    monkeypatch.delenv("MOBIUS_TELEMETRY_TOKEN", raising=False)
    assert _settings().telemetry_authentication is None


def test_signal_catalog_is_closed_and_has_no_private_labels() -> None:
    assert len(METRIC_CATALOG) >= 50
    for name, definition in METRIC_CATALOG.items():
        assert name.startswith("mobius.")
        assert definition.unit
        assert definition.owner
        assert definition.objective
        assert definition.dashboard
        assert definition.runbook
        assert not set(definition.allowed_labels).intersection(definition.prohibited_labels)


def test_observability_manifests_are_versioned_and_cross_linked() -> None:
    manifests = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in OBSERVABILITY_DOCS.glob("*.json")
    }
    assert set(manifests) == {
        "alerts-v1.json",
        "dashboards-v1.json",
        "signals-v1.json",
        "slos-v1.json",
    }
    signals = manifests["signals-v1.json"]
    dashboards = manifests["dashboards-v1.json"]
    alerts = manifests["alerts-v1.json"]
    slos = manifests["slos-v1.json"]
    assert signals["version"] == "mobius-signals-v1"
    assert {item["name"] for item in signals["signals"]} == set(METRIC_CATALOG)
    dashboard_ids = {item["id"] for item in dashboards["dashboards"]}
    alert_ids = {item["id"] for item in alerts["alerts"]}
    objective_ids = {item["id"] for item in slos["objectives"]}
    assert dashboard_ids
    assert alert_ids
    assert objective_ids == {"mobius-internal-slos-v1"}
    for dashboard in dashboards["dashboards"]:
        assert 5 <= dashboard["windowMinutes"] <= 1_440
        assert dashboard["missingData"] in {
            "breach",
            "unknown",
            "unavailable",
            "not-applicable",
        }
        assert dashboard["runbook"]
        assert dashboard["panels"]
    for alert in alerts["alerts"]:
        assert alert["query"]
        assert alert["firingRule"]
        assert alert["recoveryRule"]
        assert alert["missingData"] in {"breach", "hold", "healthy"}
        assert alert["runbook"]
        assert alert["objective"] in objective_ids
        assert alert["groupBy"] in (["alertId", "environment"], ["alertId", "deployment"])
        threshold = float(alert["threshold"])
        comparison = alert.get("comparison", "gte")
        margin = max(abs(threshold) * 0.5, 1.0)
        recovery_threshold = threshold - margin if comparison == "gte" else threshold + margin
        rule = AlertRule(
            alert_id=alert["id"],
            threshold=threshold,
            recovery_threshold=recovery_threshold,
            firing_windows=1,
            recovery_windows=1,
            missing_data=alert["missingData"],
            comparison=comparison,
        )
        evaluator = AlertEvaluator()
        breach_value = threshold + 1 if comparison == "gte" else threshold - 1
        firing = evaluator.evaluate(rule, AlertState(), breach_value)
        assert firing.firing is True
        recovered = evaluator.evaluate(rule, firing, rule.recovery_threshold)
        assert recovered.firing is False
    assert all(item["targetStatus"] == "provisional" for item in slos["objectives"])


def test_no_capture_vocabulary_is_present_in_exportable_schema() -> None:
    exported_schema = json.dumps(
        {
            "events": sorted(
                {
                    "api.request.completed",
                    "security.control.triggered",
                    "telemetry.export.failed",
                }
            ),
            "logFields": sorted(
                {
                    "operation",
                    "route",
                    "method",
                    "status_class",
                    "outcome",
                    "failure_class",
                    "correlation",
                }
            ),
            "spanAttributes": ["operation", "component", "outcome", "correlation"],
        }
    )
    for prohibited in (
        "chain_of_thought",
        "prompt",
        "response",
        "source_text",
        "sql_parameters",
        "provider_payload",
        "authorization",
        "cookie",
    ):
        assert prohibited not in exported_schema
