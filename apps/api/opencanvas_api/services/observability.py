from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

import httpx
import structlog
from pydantic import SecretStr

from opencanvas_api.core.config import AppMode, Settings

SCHEMA_VERSION = "mobius-operational-v1"
SIGNAL_CATALOG_VERSION = "mobius-signals-v1"
TRACE_VERSION = "00"
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SAFE_CORRELATION = re.compile(r"^[a-f0-9]{20}$")
_TRACEPARENT = re.compile(r"^00-(?P<trace>[a-f0-9]{32})-(?P<span>[a-f0-9]{16})-(?P<flags>0[01])$")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_IPV4 = re.compile(
    r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"
)
_TOKEN = re.compile(
    r"(?i)(?:bearer\s+)?(?:"
    r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16})"
)
_CONNECTION_SECRET = re.compile(
    r"(?i)(?:password|passwd|pwd|accountkey|access[_-]?token|refresh[_-]?token|"
    r"api[_-]?key|client[_-]?secret|sharedaccesssignature)\s*[:=]\s*[^\s,;]+"
)
_SIGNED_QUERY = re.compile(r"(?i)([?&](?:sig|signature|token|key|code|se|sp|sv)=[^&#\s]+)")

FORBIDDEN_FIELD_PARTS = frozenset(
    {
        "access_key",
        "access_token",
        "approval_token",
        "authorization",
        "body",
        "chain_of_thought",
        "content",
        "cookie",
        "credential",
        "document_text",
        "email",
        "filename",
        "grant_token",
        "identity_header",
        "invitation_token",
        "object_path",
        "password",
        "payload",
        "private_key",
        "prompt",
        "provider_payload",
        "query_string",
        "receipt_handle",
        "recovery_token",
        "refresh_token",
        "response",
        "session",
        "signed_url",
        "source_text",
        "sql_parameters",
        "storage_key",
        "token",
    }
)

LOG_FIELD_LIMITS: Mapping[str, int] = {
    "operation": 64,
    "route": 96,
    "method": 8,
    "status_class": 3,
    "outcome": 24,
    "failure_class": 48,
    "dependency": 32,
    "state": 24,
    "reason": 48,
    "policy_version": 48,
    "objective_version": 48,
    "correlation_kind": 24,
    "correlation": 20,
    "linked_correlation": 20,
    "duration_ms": 16,
    "count": 16,
    "size_bytes": 20,
    "status_code": 3,
    "retry_count": 8,
    "dropped_count": 16,
}

ALLOWED_EVENT_NAMES = frozenset(
    {
        "api.request.completed",
        "api.request.failed",
        "dependency.state.changed",
        "durable_job.transition",
        "integrity.check.completed",
        "operator.health.accessed",
        "outbox.delivery.completed",
        "provider.call.completed",
        "security.control.triggered",
        "telemetry.export.failed",
        "telemetry.export.recovered",
        "telemetry.signal.dropped",
        "worker.state.changed",
    }
)

ALLOWED_SPAN_NAMES = frozenset(
    {
        "http.server.request",
        "database.transaction",
        "storage.operation",
        "scanner.operation",
        "durable_job.request",
        "durable_job.delivery",
        "durable_job.attempt",
        "worker.execution",
        "indexer.stage",
        "provider.call",
        "domain_event.publish",
        "outbox.delivery",
        "workflow.execution",
        "agent.execution",
    }
)

SPAN_ATTRIBUTE_LIMITS: Mapping[str, int] = {
    "operation": 64,
    "component": 32,
    "outcome": 24,
    "failure_class": 48,
    "status_class": 3,
    "correlation": 20,
    "linked_correlation": 20,
}


class SignalKind(StrEnum):
    APPLICATION_LOG = "application_log"
    SECURITY_LOG = "security_log"
    METRIC = "metric"
    SPAN = "span"


class Severity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class OperationalHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    INDETERMINATE = "indeterminate"
    DISABLED = "disabled"


class MetricType(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    purpose: str
    metric_type: MetricType
    unit: str
    aggregation: str
    allowed_labels: Mapping[str, frozenset[str]]
    max_series: int
    owner: str
    objective: str
    alert: str | None
    dashboard: str
    runbook: str
    histogram_boundaries: tuple[float, ...] = ()
    prohibited_labels: tuple[str, ...] = (
        "user",
        "workspace",
        "canvas",
        "document",
        "resource",
        "request",
        "job",
        "ip",
        "url",
        "object",
        "prompt",
    )


_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "other"})
_OUTCOMES = frozenset({"success", "client_error", "server_error", "denied", "unavailable", "other"})
_STATES = frozenset({"healthy", "degraded", "unavailable", "indeterminate", "other"})
_COMPONENTS = frozenset(
    {
        "api",
        "database",
        "storage",
        "scanner",
        "queue",
        "worker",
        "limiter",
        "indexer",
        "provider",
        "event",
        "outbox",
        "audit",
        "trace",
        "backup",
        "telemetry",
        "capacity",
        "cost",
        "other",
    }
)


def _metric(
    name: str,
    purpose: str,
    metric_type: MetricType,
    unit: str,
    *,
    labels: Mapping[str, frozenset[str]] | None = None,
    boundaries: tuple[float, ...] = (),
    alert: str | None = None,
    dashboard: str = "service-overview-v1",
    runbook: str = "OBSERVABILITY_OPERATIONS_RUNBOOK.md",
) -> MetricDefinition:
    return MetricDefinition(
        name=name,
        purpose=purpose,
        metric_type=metric_type,
        unit=unit,
        aggregation="sum" if metric_type is MetricType.COUNTER else "last",
        allowed_labels=labels or {"component": _COMPONENTS, "outcome": _OUTCOMES},
        max_series=128,
        owner="platform-operations",
        objective="mobius-internal-slos-v1",
        alert=alert,
        dashboard=dashboard,
        runbook=runbook,
        histogram_boundaries=boundaries,
    )


METRIC_CATALOG: Mapping[str, MetricDefinition] = {
    definition.name: definition
    for definition in (
        _metric(
            "mobius.api.requests",
            "Bounded API request volume.",
            MetricType.COUNTER,
            "request",
            labels={"method": _METHODS, "outcome": _OUTCOMES},
        ),
        _metric(
            "mobius.api.duration",
            "API server duration.",
            MetricType.HISTOGRAM,
            "ms",
            labels={"method": _METHODS, "outcome": _OUTCOMES},
            boundaries=(5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000),
            alert="api-latency-v1",
        ),
        _metric("mobius.api.errors", "API failures.", MetricType.COUNTER, "error"),
        _metric("mobius.api.saturation", "API concurrency saturation.", MetricType.GAUGE, "ratio"),
        _metric(
            "mobius.database.pool.acquire",
            "Database pool acquisition duration.",
            MetricType.HISTOGRAM,
            "ms",
            boundaries=(1, 5, 10, 25, 50, 100, 250, 500, 1_000),
            alert="database-saturation-v1",
            dashboard="database-v1",
        ),
        _metric(
            "mobius.database.timeouts", "Database timeout count.", MetricType.COUNTER, "timeout"
        ),
        _metric(
            "mobius.database.transactions", "Database outcomes.", MetricType.COUNTER, "transaction"
        ),
        _metric("mobius.database.lock_wait", "Database lock wait.", MetricType.HISTOGRAM, "ms"),
        _metric(
            "mobius.storage.operations",
            "Private object operations.",
            MetricType.COUNTER,
            "operation",
        ),
        _metric("mobius.storage.duration", "Private object latency.", MetricType.HISTOGRAM, "ms"),
        _metric(
            "mobius.storage.failures", "Private object failures.", MetricType.COUNTER, "failure"
        ),
        _metric(
            "mobius.scanner.throughput", "Scanner verdict throughput.", MetricType.COUNTER, "object"
        ),
        _metric("mobius.scanner.duration", "Scanner verdict latency.", MetricType.HISTOGRAM, "ms"),
        _metric(
            "mobius.scanner.unavailable",
            "Scanner unavailable results.",
            MetricType.COUNTER,
            "failure",
        ),
        _metric("mobius.scanner.quarantine", "Quarantine outcomes.", MetricType.COUNTER, "object"),
        _metric("mobius.queue.depth", "Eligible durable job depth.", MetricType.GAUGE, "job"),
        _metric(
            "mobius.queue.oldest_age",
            "Oldest eligible durable job age.",
            MetricType.GAUGE,
            "s",
            alert="queue-backlog-v1",
            dashboard="durable-work-v1",
        ),
        _metric(
            "mobius.queue.claim_duration", "Durable claim latency.", MetricType.HISTOGRAM, "ms"
        ),
        _metric("mobius.queue.lease_loss", "Lease-loss count.", MetricType.COUNTER, "lease"),
        _metric("mobius.queue.retries", "Bounded retry count.", MetricType.COUNTER, "retry"),
        _metric("mobius.queue.cancellations", "Cancellation count.", MetricType.COUNTER, "job"),
        _metric("mobius.queue.dead_letters", "Dead-letter count.", MetricType.COUNTER, "job"),
        _metric("mobius.queue.replays", "Authorized replay count.", MetricType.COUNTER, "job"),
        _metric(
            "mobius.queue.stale_suppression", "Stale result fences.", MetricType.COUNTER, "result"
        ),
        _metric("mobius.limiter.health", "Shared limiter health.", MetricType.GAUGE, "state"),
        _metric("mobius.limiter.duration", "Shared limiter latency.", MetricType.HISTOGRAM, "ms"),
        _metric(
            "mobius.limiter.denials", "Shared limiter denials.", MetricType.COUNTER, "decision"
        ),
        _metric(
            "mobius.limiter.saturation",
            "Shared limiter saturation.",
            MetricType.COUNTER,
            "decision",
        ),
        _metric("mobius.limiter.bypass", "Limiter bypass attempts.", MetricType.COUNTER, "attempt"),
        _metric("mobius.indexer.throughput", "Indexer revisions.", MetricType.COUNTER, "revision"),
        _metric(
            "mobius.indexer.stage_duration", "Indexer stage latency.", MetricType.HISTOGRAM, "ms"
        ),
        _metric("mobius.indexer.freshness", "Published index age.", MetricType.GAUGE, "s"),
        _metric(
            "mobius.indexer.coverage", "Clean-source index coverage.", MetricType.GAUGE, "ratio"
        ),
        _metric("mobius.indexer.drift", "Deterministic drift.", MetricType.COUNTER, "mismatch"),
        _metric(
            "mobius.indexer.deduplication", "Deduplicated requests.", MetricType.COUNTER, "request"
        ),
        _metric(
            "mobius.indexer.publication_conflict",
            "Publication fences.",
            MetricType.COUNTER,
            "conflict",
        ),
        _metric(
            "mobius.indexer.cancellations", "Indexer cancellations.", MetricType.COUNTER, "revision"
        ),
        _metric("mobius.indexer.failures", "Indexer failures.", MetricType.COUNTER, "failure"),
        _metric("mobius.provider.calls", "External provider calls.", MetricType.COUNTER, "call"),
        _metric("mobius.provider.duration", "Provider latency.", MetricType.HISTOGRAM, "ms"),
        _metric("mobius.provider.usage", "Bounded provider usage.", MetricType.COUNTER, "unit"),
        _metric("mobius.provider.cost", "Estimated provider cost.", MetricType.COUNTER, "usd"),
        _metric("mobius.outbox.backlog", "Pending outbox deliveries.", MetricType.GAUGE, "event"),
        _metric("mobius.outbox.oldest_age", "Oldest outbox age.", MetricType.GAUGE, "s"),
        _metric("mobius.outbox.attempts", "Outbox attempts.", MetricType.COUNTER, "attempt"),
        _metric(
            "mobius.outbox.terminal_failure",
            "Terminal outbox failures.",
            MetricType.COUNTER,
            "event",
        ),
        _metric(
            "mobius.evidence.integrity",
            "Audit/Trace/event integrity findings.",
            MetricType.GAUGE,
            "finding",
        ),
        _metric("mobius.backup.freshness", "Backup freshness prerequisite.", MetricType.GAUGE, "s"),
        _metric(
            "mobius.capacity.utilization",
            "Bounded capacity utilization.",
            MetricType.GAUGE,
            "ratio",
        ),
        _metric(
            "mobius.cost.estimated", "Bounded operational cost estimate.", MetricType.GAUGE, "usd"
        ),
        _metric(
            "mobius.telemetry.export_health",
            "Exporter health.",
            MetricType.GAUGE,
            "state",
            alert="telemetry-loss-v1",
            dashboard="telemetry-pipeline-v1",
        ),
        _metric(
            "mobius.telemetry.dropped",
            "Rejected or dropped signals.",
            MetricType.COUNTER,
            "signal",
            alert="telemetry-loss-v1",
            dashboard="telemetry-pipeline-v1",
        ),
        _metric("mobius.telemetry.buffer", "Telemetry buffer use.", MetricType.GAUGE, "signal"),
    )
}


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    span_id: str
    sampled: bool
    depth: int = 0

    @property
    def traceparent(self) -> str:
        return f"{TRACE_VERSION}-{self.trace_id}-{self.span_id}-{'01' if self.sampled else '00'}"


@dataclass(frozen=True, slots=True)
class SpanLink:
    trace_id: str
    span_id: str
    correlation: str | None = None


@dataclass(frozen=True, slots=True)
class OperationalSignal:
    kind: SignalKind
    name: str
    timestamp: str
    service: str
    component: str
    environment: str
    release: str
    deployment: str
    payload: Mapping[str, object]
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class TelemetryCounters:
    accepted: int = 0
    rejected: int = 0
    dropped: int = 0
    exported: int = 0
    export_failures: int = 0
    export_timeouts: int = 0
    buffer_high_watermark: int = 0
    last_success_monotonic: float | None = None


class TelemetrySink(Protocol):
    async def export(self, signals: Sequence[OperationalSignal]) -> None: ...

    async def close(self) -> None: ...


class InMemoryTelemetrySink:
    """Bounded local test sink; production configuration rejects it."""

    def __init__(self, *, fail: bool = False, delay_seconds: float = 0.0) -> None:
        self.signals: list[OperationalSignal] = []
        self.fail = fail
        self.delay_seconds = delay_seconds
        self.closed = False

    async def export(self, signals: Sequence[OperationalSignal]) -> None:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise RuntimeError("telemetry_sink_unavailable")
        self.signals.extend(signals)

    async def close(self) -> None:
        self.closed = True


class DisabledTelemetrySink:
    async def export(self, signals: Sequence[OperationalSignal]) -> None:
        del signals

    async def close(self) -> None:
        return None


class HttpTelemetrySink:
    """Provider-neutral bounded JSON exporter over verified HTTPS."""

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: float,
        authentication: SecretStr | None,
        verify_tls: bool,
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if authentication is not None:
            headers["Authorization"] = f"Bearer {authentication.get_secret_value()}"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            verify=verify_tls,
            headers=headers,
        )
        self._endpoint = endpoint

    async def export(self, signals: Sequence[OperationalSignal]) -> None:
        response = await self._client.post(
            self._endpoint,
            content=json.dumps(
                {
                    "resource": {"schema": SCHEMA_VERSION},
                    "signals": [signal.as_dict() for signal in signals],
                },
                separators=(",", ":"),
            ),
        )
        response.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()


@dataclass(slots=True)
class SpanHandle:
    telemetry: OperationalTelemetry
    context: TraceContext
    name: str
    component: str
    started_monotonic: float
    attributes: dict[str, str]
    links: tuple[SpanLink, ...]
    events: list[Mapping[str, str]] = field(default_factory=list)
    token: contextvars.Token[TraceContext | None] | None = None
    ended: bool = False

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        if self.ended or len(self.events) >= self.telemetry.max_span_events:
            return
        if not _SAFE_NAME.fullmatch(name):
            return
        sanitized = self.telemetry.sanitize_fields(
            attributes or {},
            allowlist=SPAN_ATTRIBUTE_LIMITS,
        )
        self.events.append({"name": name, **sanitized})

    def end(
        self,
        *,
        outcome: str,
        failure_class: str | None = None,
    ) -> None:
        if self.ended:
            return
        self.ended = True
        self.telemetry.finish_span(
            self,
            outcome=outcome,
            failure_class=failure_class,
        )


_current_trace: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "mobius_operational_trace",
    default=None,
)


class OperationalTelemetry:
    """One bounded, non-authoritative operational telemetry boundary."""

    def __init__(
        self,
        *,
        service: str,
        environment: str,
        release: str,
        deployment: str,
        pseudonymization_secret: SecretStr,
        sink: TelemetrySink,
        enabled: bool,
        batch_size: int,
        buffer_size: int,
        export_timeout_seconds: float,
        retry_limit: int,
        shutdown_timeout_seconds: float,
        sample_ratio: float,
        max_span_depth: int,
        max_span_events: int,
        max_span_attributes: int,
        failure_threshold: int,
        cardinality_budget: int,
        baggage_allowlist: Sequence[str],
    ) -> None:
        self.service = service
        self.environment = environment
        self.release = release
        self.deployment = deployment
        self._secret = pseudonymization_secret.get_secret_value().encode()
        self._sink = sink
        self.enabled = enabled
        self._buffer: deque[OperationalSignal] = deque()
        self._batch_size = batch_size
        self._buffer_size = buffer_size
        self._export_timeout_seconds = export_timeout_seconds
        self._retry_limit = retry_limit
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._sample_ratio = sample_ratio
        self._max_span_depth = max_span_depth
        self.max_span_events = max_span_events
        self._max_span_attributes = max_span_attributes
        self._failure_threshold = failure_threshold
        self._cardinality_budget = cardinality_budget
        self._baggage_allowlist = frozenset(baggage_allowlist)
        self._series: dict[str, set[tuple[tuple[str, str], ...]]] = defaultdict(set)
        self._flush_lock = asyncio.Lock()
        self._scheduled_flush: asyncio.Task[bool] | None = None
        self._consecutive_failures = 0
        self.counters = TelemetryCounters()
        self._logger = structlog.get_logger("opencanvas_api.operational")

    @property
    def max_span_attributes(self) -> int:
        return self._max_span_attributes

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    def health(self) -> OperationalHealth:
        if not self.enabled:
            return OperationalHealth.DISABLED
        if self._consecutive_failures >= self._failure_threshold:
            return OperationalHealth.UNAVAILABLE
        if self._consecutive_failures or self.counters.dropped or self.counters.rejected:
            return OperationalHealth.DEGRADED
        return OperationalHealth.HEALTHY

    def correlate(self, kind: str, value: object, *, scope: Sequence[object] = ()) -> str:
        if not _SAFE_NAME.fullmatch(kind):
            raise ValueError("Correlation kind is not allowlisted.")
        material = "\x1f".join(
            [SCHEMA_VERSION, self.environment, self.deployment, kind]
            + [str(item) for item in scope]
            + [str(value)]
        )
        return hmac.new(self._secret, material.encode(), hashlib.sha256).hexdigest()[:20]

    def span_link(self, kind: str, value: object, *, scope: Sequence[object] = ()) -> SpanLink:
        correlation = self.correlate(kind, value, scope=scope)
        digest = hmac.new(
            self._secret,
            f"span-link\x1f{correlation}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return SpanLink(
            trace_id=digest[:32],
            span_id=digest[32:48],
            correlation=correlation,
        )

    def sanitize_fields(
        self,
        fields: Mapping[str, object],
        *,
        allowlist: Mapping[str, int] = LOG_FIELD_LIMITS,
    ) -> dict[str, str]:
        if len(fields) > len(allowlist):
            raise ValueError("Operational field count exceeds its schema.")
        sanitized: dict[str, str] = {}
        for key, raw_value in fields.items():
            lowered = key.lower()
            if (
                key not in allowlist
                or any(part in lowered for part in FORBIDDEN_FIELD_PARTS)
                or raw_value is None
            ):
                raise ValueError(f"Operational field {key!r} is not allowed.")
            value = _redact(str(raw_value), limit=allowlist[key])
            sanitized[key] = value
        return sanitized

    def emit_log(
        self,
        *,
        event_name: str,
        severity: Severity,
        component: str,
        fields: Mapping[str, object],
        security: bool = False,
        trace: TraceContext | None = None,
    ) -> bool:
        if event_name not in ALLOWED_EVENT_NAMES or component not in _COMPONENTS:
            self.counters.rejected += 1
            return False
        try:
            payload: dict[str, object] = {
                "severity": severity.value,
                **self.sanitize_fields(fields),
            }
        except ValueError:
            self.counters.rejected += 1
            return False
        context = trace or _current_trace.get()
        if context is not None:
            payload["trace_id"] = context.trace_id
            payload["span_id"] = context.span_id
        signal = self._signal(
            kind=SignalKind.SECURITY_LOG if security else SignalKind.APPLICATION_LOG,
            name=event_name,
            component=component,
            payload=payload,
        )
        accepted = self._enqueue(signal)
        if accepted:
            log_method = getattr(self._logger, severity.value)
            log_method("operational_event", **signal.as_dict())
        return accepted

    def record_metric(
        self,
        name: str,
        value: float | int,
        *,
        labels: Mapping[str, str],
    ) -> bool:
        definition = METRIC_CATALOG.get(name)
        if definition is None or not isinstance(value, (int, float)):
            self.counters.rejected += 1
            return False
        if value < 0 or value != value or value in {float("inf"), float("-inf")}:
            self.counters.rejected += 1
            return False
        normalized: dict[str, str] = {}
        if set(labels) != set(definition.allowed_labels):
            self.counters.rejected += 1
            return False
        for key, raw in labels.items():
            allowed = definition.allowed_labels[key]
            normalized[key] = raw if raw in allowed else ("other" if "other" in allowed else "")
            if not normalized[key]:
                self.counters.rejected += 1
                return False
        series = tuple(sorted(normalized.items()))
        budget = min(definition.max_series, self._cardinality_budget)
        known = self._series[name]
        if series not in known and len(known) >= budget:
            self.counters.rejected += 1
            return False
        known.add(series)
        return self._enqueue(
            self._signal(
                kind=SignalKind.METRIC,
                name=name,
                component=normalized.get("component", "api"),
                payload={
                    "catalog_version": SIGNAL_CATALOG_VERSION,
                    "type": definition.metric_type.value,
                    "unit": definition.unit,
                    "value": value,
                    "labels": normalized,
                },
            )
        )

    def start_span(
        self,
        name: str,
        *,
        component: str,
        parent: TraceContext | None = None,
        links: Sequence[SpanLink] = (),
        attributes: Mapping[str, object] | None = None,
    ) -> SpanHandle:
        if name not in ALLOWED_SPAN_NAMES or component not in _COMPONENTS:
            raise ValueError("Operational span is not allowlisted.")
        inherited = parent or _current_trace.get()
        depth = 0 if inherited is None else inherited.depth + 1
        if depth > self._max_span_depth:
            depth = self._max_span_depth
            inherited = None
        sampled = _sample(
            inherited.trace_id if inherited is not None else None,
            self._sample_ratio,
        )
        context = TraceContext(
            trace_id=inherited.trace_id if inherited is not None else secrets.token_hex(16),
            span_id=secrets.token_hex(8),
            sampled=sampled,
            depth=depth,
        )
        safe_attributes = self.sanitize_fields(
            dict(attributes or {}),
            allowlist=SPAN_ATTRIBUTE_LIMITS,
        )
        if len(safe_attributes) > self._max_span_attributes:
            safe_attributes = dict(list(safe_attributes.items())[: self._max_span_attributes])
        bounded_links = tuple(links[:8])
        handle = SpanHandle(
            telemetry=self,
            context=context,
            name=name,
            component=component,
            started_monotonic=time.perf_counter(),
            attributes=safe_attributes,
            links=bounded_links,
        )
        handle.token = _current_trace.set(context)
        return handle

    def finish_span(
        self,
        handle: SpanHandle,
        *,
        outcome: str,
        failure_class: str | None,
    ) -> None:
        if handle.token is not None:
            _current_trace.reset(handle.token)
        if not handle.context.sampled:
            return
        safe_outcome = outcome if outcome in _OUTCOMES else "other"
        payload: dict[str, object] = {
            "trace_id": handle.context.trace_id,
            "span_id": handle.context.span_id,
            "depth": handle.context.depth,
            "duration_ms": round((time.perf_counter() - handle.started_monotonic) * 1_000, 3),
            "outcome": safe_outcome,
            "attributes": handle.attributes,
            "events": tuple(handle.events[: self.max_span_events]),
            "links": tuple(asdict(link) for link in handle.links),
        }
        if failure_class is not None:
            payload["failure_class"] = _redact(failure_class, limit=48)
        self._enqueue(
            self._signal(
                kind=SignalKind.SPAN,
                name=handle.name,
                component=handle.component,
                payload=payload,
            )
        )

    def safe_baggage(self, baggage: Mapping[str, str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in baggage.items():
            if key in self._baggage_allowlist and _SAFE_NAME.fullmatch(key):
                result[key] = _redact(value, limit=48)
        return result

    async def flush(self) -> bool:
        if not self.enabled or not self._buffer:
            return True
        async with self._flush_lock:
            batch = [
                self._buffer.popleft() for _ in range(min(self._batch_size, len(self._buffer)))
            ]
            for attempt in range(self._retry_limit + 1):
                try:
                    await asyncio.wait_for(
                        self._sink.export(batch),
                        timeout=self._export_timeout_seconds,
                    )
                except TimeoutError:
                    self.counters.export_timeouts += 1
                    self.counters.export_failures += 1
                except Exception:
                    self.counters.export_failures += 1
                else:
                    self.counters.exported += len(batch)
                    self.counters.last_success_monotonic = time.monotonic()
                    self._consecutive_failures = 0
                    return True
                if attempt < self._retry_limit:
                    await asyncio.sleep(min(0.05 * (2**attempt), 0.25))
            self._consecutive_failures += 1
            available = self._buffer_size - len(self._buffer)
            retained = batch[-available:] if available > 0 else []
            for signal in reversed(retained):
                self._buffer.appendleft(signal)
            dropped = len(batch) - len(retained)
            self.counters.dropped += dropped
            return False

    def schedule_flush(self) -> None:
        if (
            not self.enabled
            or len(self._buffer) < self._batch_size
            or (self._scheduled_flush is not None and not self._scheduled_flush.done())
        ):
            return
        self._scheduled_flush = asyncio.create_task(self.flush())

    async def close(self) -> bool:
        success = True
        if self._scheduled_flush is not None and not self._scheduled_flush.done():
            try:
                success = await asyncio.wait_for(
                    self._scheduled_flush,
                    timeout=self._shutdown_timeout_seconds,
                )
            except TimeoutError:
                self._scheduled_flush.cancel()
                success = False
        deadline = time.monotonic() + self._shutdown_timeout_seconds
        while self._buffer and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                flushed = await asyncio.wait_for(self.flush(), timeout=max(0.001, remaining))
            except TimeoutError:
                flushed = False
            success = success and flushed
            if not flushed:
                break
        if self._buffer:
            self.counters.dropped += len(self._buffer)
            self._buffer.clear()
            success = False
        await self._sink.close()
        return success

    def _signal(
        self,
        *,
        kind: SignalKind,
        name: str,
        component: str,
        payload: Mapping[str, object],
    ) -> OperationalSignal:
        return OperationalSignal(
            kind=kind,
            name=name,
            timestamp=datetime.now(UTC).isoformat(),
            service=self.service,
            component=component,
            environment=self.environment,
            release=self.release,
            deployment=self.deployment,
            payload=payload,
        )

    def _enqueue(self, signal: OperationalSignal) -> bool:
        if not self.enabled:
            return False
        if len(self._buffer) >= self._buffer_size:
            self.counters.dropped += 1
            return False
        self._buffer.append(signal)
        self.counters.accepted += 1
        self.counters.buffer_high_watermark = max(
            self.counters.buffer_high_watermark,
            len(self._buffer),
        )
        return True


@dataclass(frozen=True, slots=True)
class IntegritySnapshot:
    audit_sequence_gaps: int = 0
    trace_parent_gaps: int = 0
    event_outbox_orphans: int = 0
    evidence_link_orphans: int = 0
    impossible_transitions: int = 0
    stale_backlog: int = 0
    duplicate_durable_identities: int = 0
    append_only_mutations: int = 0
    telemetry_gaps: int = 0


@dataclass(frozen=True, slots=True)
class IntegrityFinding:
    classification: str
    severity: str
    count: int


def assess_integrity(snapshot: IntegritySnapshot) -> tuple[IntegrityFinding, ...]:
    severities = {
        "audit_sequence_gaps": "critical",
        "trace_parent_gaps": "critical",
        "event_outbox_orphans": "critical",
        "evidence_link_orphans": "high",
        "impossible_transitions": "high",
        "stale_backlog": "warning",
        "duplicate_durable_identities": "critical",
        "append_only_mutations": "critical",
        "telemetry_gaps": "warning",
    }
    return tuple(
        IntegrityFinding(classification=name, severity=severities[name], count=count)
        for name, count in asdict(snapshot).items()
        if count > 0
    )


@dataclass(frozen=True, slots=True)
class AlertRule:
    alert_id: str
    threshold: float
    recovery_threshold: float
    firing_windows: int
    recovery_windows: int
    missing_data: str
    comparison: Literal["gte", "lte"] = "gte"


@dataclass(slots=True)
class AlertState:
    firing: bool = False
    breach_windows: int = 0
    recovery_windows: int = 0
    notifications: int = 0


class AlertEvaluator:
    """Deterministic firing, recovery, missing-data, and storm-dedup contract."""

    def evaluate(
        self,
        rule: AlertRule,
        state: AlertState,
        value: float | None,
    ) -> AlertState:
        next_state = replace(state)
        if value is None:
            if rule.missing_data == "breach":
                breached = True
            elif rule.missing_data == "healthy":
                breached = False
            else:
                return next_state
        else:
            if rule.comparison == "gte":
                breached = (
                    value >= rule.threshold if not state.firing else value > rule.recovery_threshold
                )
            else:
                breached = (
                    value <= rule.threshold if not state.firing else value < rule.recovery_threshold
                )
        if breached:
            next_state.breach_windows += 1
            next_state.recovery_windows = 0
            if not next_state.firing and next_state.breach_windows >= rule.firing_windows:
                next_state.firing = True
                next_state.notifications += 1
        else:
            next_state.breach_windows = 0
            next_state.recovery_windows += 1
            if next_state.firing and next_state.recovery_windows >= rule.recovery_windows:
                next_state.firing = False
                next_state.notifications += 1
        return next_state


def parse_traceparent(value: str | None) -> TraceContext | None:
    if not value:
        return None
    match = _TRACEPARENT.fullmatch(value.strip().lower())
    if match is None or match["trace"] == "0" * 32 or match["span"] == "0" * 16:
        return None
    return TraceContext(
        trace_id=match["trace"],
        span_id=match["span"],
        sampled=match["flags"] == "01",
    )


def build_observability(
    settings: Settings,
    *,
    sink: TelemetrySink | None = None,
) -> OperationalTelemetry:
    selected_sink = sink
    if selected_sink is None:
        if settings.telemetry_exporter == "memory":
            selected_sink = InMemoryTelemetrySink()
        elif settings.telemetry_exporter == "http":
            if settings.telemetry_endpoint is None:
                raise RuntimeError("The telemetry endpoint is unavailable.")
            if (
                settings.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}
                and settings.telemetry_authentication is None
            ):
                raise RuntimeError("The telemetry authentication secret is unavailable.")
            selected_sink = HttpTelemetrySink(
                endpoint=settings.telemetry_endpoint,
                timeout_seconds=settings.telemetry_export_timeout_seconds,
                authentication=settings.telemetry_authentication,
                verify_tls=settings.telemetry_tls_verify,
            )
        else:
            selected_sink = DisabledTelemetrySink()
    return OperationalTelemetry(
        service=settings.telemetry_service_name,
        environment=settings.runtime_mode.value,
        release=settings.telemetry_release,
        deployment=settings.telemetry_deployment,
        pseudonymization_secret=SecretStr(settings.telemetry_pseudonymization_secret),
        sink=selected_sink,
        enabled=settings.telemetry_enabled,
        batch_size=settings.telemetry_batch_size,
        buffer_size=settings.telemetry_buffer_size,
        export_timeout_seconds=settings.telemetry_export_timeout_seconds,
        retry_limit=settings.telemetry_retry_limit,
        shutdown_timeout_seconds=settings.telemetry_shutdown_timeout_seconds,
        sample_ratio=settings.telemetry_sample_ratio,
        max_span_depth=settings.telemetry_max_span_depth,
        max_span_events=settings.telemetry_max_span_events,
        max_span_attributes=settings.telemetry_max_span_attributes,
        failure_threshold=settings.telemetry_health_failure_threshold,
        cardinality_budget=settings.telemetry_cardinality_budget,
        baggage_allowlist=settings.telemetry_baggage_allowlist,
    )


def classify_http_outcome(status_code: int) -> str:
    if status_code < 400:
        return "success"
    if status_code < 500:
        return "client_error"
    return "server_error"


def safe_route_template(route: object) -> str:
    path = getattr(route, "path", None)
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 96:
        return "unmatched"
    return _CONTROL_CHARACTERS.sub("", path)


def current_trace_context() -> TraceContext | None:
    return _current_trace.get()


def _sample(trace_id: str | None, ratio: float) -> bool:
    if ratio <= 0:
        return False
    if ratio >= 1:
        return True
    material = trace_id or secrets.token_hex(16)
    return int(hashlib.sha256(material.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < ratio


def _redact(value: str, *, limit: int) -> str:
    sanitized = _CONTROL_CHARACTERS.sub(" ", value).strip()
    sanitized = _EMAIL.sub("[redacted-email]", sanitized)
    sanitized = _IPV4.sub("[redacted-ip]", sanitized)
    sanitized = _TOKEN.sub("[redacted-token]", sanitized)
    sanitized = _CONNECTION_SECRET.sub("[redacted-secret]", sanitized)
    sanitized = _SIGNED_QUERY.sub("?redacted", sanitized)
    return sanitized[:limit]


__all__ = [
    "ALLOWED_EVENT_NAMES",
    "ALLOWED_SPAN_NAMES",
    "FORBIDDEN_FIELD_PARTS",
    "METRIC_CATALOG",
    "SCHEMA_VERSION",
    "SIGNAL_CATALOG_VERSION",
    "AlertEvaluator",
    "AlertRule",
    "AlertState",
    "HttpTelemetrySink",
    "InMemoryTelemetrySink",
    "IntegrityFinding",
    "IntegritySnapshot",
    "MetricDefinition",
    "MetricType",
    "OperationalHealth",
    "OperationalSignal",
    "OperationalTelemetry",
    "Severity",
    "SignalKind",
    "SpanHandle",
    "SpanLink",
    "TelemetryCounters",
    "TraceContext",
    "assess_integrity",
    "build_observability",
    "classify_http_outcome",
    "current_trace_context",
    "parse_traceparent",
    "safe_route_template",
]
