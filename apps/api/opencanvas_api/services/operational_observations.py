"""Measured operational signals. Missing provider evidence never becomes healthy zero.

Contexts are scoped to one API request or worker iteration. Only bounded catalog
labels and numeric aggregates leave these seams; SQL, keys, content, credentials,
resource IDs and exception text are never exported.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import math
import time
import uuid
from collections.abc import Callable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, Literal, ParamSpec, TypeVar

from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from opencanvas_api.core.config import Settings
from opencanvas_api.services.observability import OperationalTelemetry, Severity

_CURRENT: contextvars.ContextVar[OperationalTelemetry | None] = contextvars.ContextVar(
    "operational_observation_telemetry", default=None
)
P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def bind_operational_telemetry(telemetry: OperationalTelemetry | None) -> Iterator[None]:
    token = _CURRENT.set(telemetry)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_telemetry() -> OperationalTelemetry | None:
    return _CURRENT.get()


def metric(name: str, value: float | int, component: str, outcome: str = "success") -> None:
    telemetry = current_telemetry()
    if telemetry is not None:
        telemetry.record_metric(name, value, labels={"component": component, "outcome": outcome})


def after_commit_metric(
    session: AsyncSession,
    name: str,
    value: float | int,
    component: str,
    outcome: str = "success",
) -> None:
    """Do not announce a durable scan/publication when its transaction rolls back."""
    telemetry = current_telemetry()
    if telemetry is None:
        return
    sync = session.sync_session
    pending = sync.info.setdefault("operational_pending_metrics", [])
    pending.append((telemetry, name, value, component, outcome))
    if not sync.info.get("operational_metric_hooks"):
        event.listen(sync, "after_commit", _committed)
        event.listen(sync, "after_rollback", _rolled_back)
        sync.info["operational_metric_hooks"] = True


def _committed(session: Session) -> None:
    if session.in_nested_transaction():
        return
    for telemetry, name, value, component, outcome in session.info.pop(
        "operational_pending_metrics", []
    ):
        telemetry.record_metric(name, value, labels={"component": component, "outcome": outcome})


def _rolled_back(session: Session) -> None:
    session.info.pop("operational_pending_metrics", None)


def measured_operation(
    component: Literal["storage", "scanner", "indexer"], operation: str
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """A real operation attempt and monotonic duration, not a provider verdict."""

    def decorate(
        function: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(function)
        async def measured(*args: P.args, **kwargs: P.kwargs) -> R:
            telemetry = current_telemetry()
            started = time.perf_counter()
            span = (
                telemetry.start_span(
                    "indexer.stage" if component == "indexer" else f"{component}.operation",
                    component=component,
                    attributes={"operation": operation},
                )
                if telemetry is not None
                else None
            )
            outcome = "success"
            failure = None
            try:
                return await function(*args, **kwargs)
            except BaseException as error:
                outcome = "other" if type(error).__name__ == "CancelledError" else "server_error"
                failure = "operation_failed"
                if component == "storage":
                    metric("mobius.storage.failures", 1, component, outcome)
                elif component == "indexer":
                    metric("mobius.indexer.failures", 1, component, outcome)
                    if getattr(error, "code", None) == "nondeterministic_dependency_output":
                        metric("mobius.indexer.drift", 1, component, "server_error")
                    if operation == "publish" and getattr(error, "code", None) in {
                        "publication_conflict",
                        "index_conflict",
                        "source_changed",
                        "authority_revoked",
                    }:
                        metric("mobius.indexer.publication_conflict", 1, component, "denied")
                raise
            finally:
                duration = (time.perf_counter() - started) * 1000
                metric(
                    "mobius.indexer.stage_duration"
                    if component == "indexer"
                    else f"mobius.{component}.duration",
                    duration,
                    component,
                    outcome,
                )
                if component == "storage":
                    metric("mobius.storage.operations", 1, component, outcome)
                if span is not None:
                    span.end(outcome=outcome, failure_class=failure)

        return measured

    return decorate


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def observe_workspace_state(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> dict[str, int | float | None]:
    """Read actual scoped publication age and referential-integrity counts.

    This check covers outbox/activity event references and retrieval publication
    references only. It never claims all audit/Trace integrity checks ran.
    No repair or incident closure occurs here. Statement deadlines remain owned
    by the configured database session.
    """
    from opencanvas_api.db.models import (
        DomainActivityEntry,
        DomainEventOutbox,
        DomainEventRecord,
        IndexPublication,
        RetrievalHead,
    )

    current = _aware(now or datetime.now(UTC))
    oldest = await session.scalar(
        select(func.min(IndexPublication.published_at))
        .join(
            RetrievalHead,
            RetrievalHead.publication_id == IndexPublication.publication_id,
        )
        .where(RetrievalHead.workspace_id == workspace_id)
    )
    age = max(0.0, (current - _aware(oldest)).total_seconds()) if oldest is not None else None
    if age is not None:
        metric("mobius.indexer.freshness", age, "indexer")
    findings = 0
    for model in (DomainEventOutbox, DomainActivityEntry):
        count = await session.scalar(
            select(func.count())
            .select_from(model)
            .outerjoin(
                DomainEventRecord,
                (model.event_id == DomainEventRecord.event_id)
                & (model.workspace_id == DomainEventRecord.workspace_id)
                & (model.user_id == DomainEventRecord.user_id),
            )
            .where(model.workspace_id == workspace_id, DomainEventRecord.event_id.is_(None))
        )
        findings += int(count or 0)
    missing_publications = await session.scalar(
        select(func.count())
        .select_from(RetrievalHead)
        .outerjoin(
            IndexPublication,
            (RetrievalHead.publication_id == IndexPublication.publication_id)
            & (RetrievalHead.workspace_id == IndexPublication.workspace_id),
        )
        .where(
            RetrievalHead.workspace_id == workspace_id,
            RetrievalHead.activation_kind == "native",
            IndexPublication.publication_id.is_(None),
        )
    )
    findings += int(missing_publications or 0)
    metric(
        "mobius.evidence.integrity", findings, "event", "server_error" if findings else "success"
    )
    telemetry = current_telemetry()
    if telemetry is not None:
        telemetry.emit_log(
            event_name="integrity.check.completed",
            component="event",
            severity=Severity.ERROR if findings else Severity.INFO,
            fields={
                "operation": "workspace_reference_integrity",
                "count": findings,
                "outcome": "server_error" if findings else "success",
            },
        )
    result: dict[str, int | float | None] = {
        "indexFreshnessSeconds": age,
        "referenceIntegrityFindings": findings,
    }
    if settings is not None:
        result.update(await observe_index_coverage(session, workspace_id, settings, now=current))
    if session.get_bind().dialect.name == "postgresql":
        result["observedLockWaitMs"] = await observe_database_lock_wait(session)
    return result


async def observe_database_lock_wait(session: AsyncSession) -> float | None:
    """Observe pending lock time, not total SQL latency or an invented healthy zero.

    PostgreSQL's waitstart is the actual start of the lock wait. Restrict the
    aggregate to sessions for the current role/database; never export PIDs/SQL.
    """
    value = await session.scalar(
        text(
            "SELECT EXTRACT(EPOCH FROM (clock_timestamp() - min(l.waitstart))) * 1000 "
            "FROM pg_catalog.pg_locks l JOIN pg_catalog.pg_stat_activity a ON a.pid=l.pid "
            "WHERE NOT l.granted AND l.waitstart IS NOT NULL "
            "AND a.usename=current_user AND a.datname=current_database()"
        )
    )
    if value is None:
        return None
    duration = max(0.0, float(value))
    metric("mobius.database.lock_wait", duration, "database")
    return duration


async def observe_index_coverage(
    session: AsyncSession, workspace_id: uuid.UUID, settings: Settings, *, now: datetime
) -> dict[str, int | float | None]:
    """Count current, nondeleted, policy-valid clean sources and their native heads."""
    from opencanvas_api.db.models import (
        Document,
        DocumentVersion,
        IndexPublication,
        IndexRevision,
        MalwareScanResult,
        ObjectPromotion,
        RetrievalHead,
        StorageObjectLifecycleTransition,
        StorageObjectVersion,
    )

    latest = (
        select(func.max(StorageObjectLifecycleTransition.sequence))
        .where(
            StorageObjectLifecycleTransition.object_version_id
            == StorageObjectVersion.object_version_id
        )
        .correlate(StorageObjectVersion)
        .scalar_subquery()
    )
    clean = (
        select(DocumentVersion.id.label("version_id"), Document.id.label("document_id"))
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(StorageObjectVersion, StorageObjectVersion.document_version_id == DocumentVersion.id)
        .join(
            ObjectPromotion,
            ObjectPromotion.target_object_version_id == StorageObjectVersion.object_version_id,
        )
        .join(MalwareScanResult, MalwareScanResult.scan_result_id == ObjectPromotion.scan_result_id)
        .join(
            StorageObjectLifecycleTransition,
            (
                StorageObjectLifecycleTransition.object_version_id
                == StorageObjectVersion.object_version_id
            )
            & (StorageObjectLifecycleTransition.sequence == latest),
        )
        .where(
            StorageObjectVersion.workspace_id == workspace_id,
            Document.current_version == DocumentVersion.version,
            Document.deleted_at.is_(None),
            DocumentVersion.deleted_at.is_(None),
            Document.status.notin_(("deleting", "deleted")),
            StorageObjectVersion.security_class == "clean",
            StorageObjectVersion.content_sha256 == DocumentVersion.content_sha256,
            StorageObjectVersion.physical_key == DocumentVersion.storage_key,
            StorageObjectLifecycleTransition.current_state == "clean",
            MalwareScanResult.outcome == "clean",
            MalwareScanResult.scanner_identity == settings.malware_scanner_identity,
            MalwareScanResult.scanner_version == settings.malware_scanner_version,
            MalwareScanResult.policy_version == settings.malware_policy_version,
            MalwareScanResult.scanned_at
            >= now - timedelta(seconds=settings.malware_scan_result_max_age_seconds),
        )
        .distinct()
        .subquery()
    )
    counts = (
        await session.execute(
            select(func.count(clean.c.version_id), func.count(IndexRevision.revision_id))
            .select_from(clean)
            .outerjoin(
                RetrievalHead,
                (RetrievalHead.document_id == clean.c.document_id)
                & (RetrievalHead.workspace_id == workspace_id)
                & (RetrievalHead.activation_kind == "native"),
            )
            .outerjoin(
                IndexPublication,
                (IndexPublication.publication_id == RetrievalHead.publication_id)
                & (IndexPublication.workspace_id == workspace_id)
                & (IndexPublication.revision_id == RetrievalHead.revision_id),
            )
            .outerjoin(
                IndexRevision,
                (IndexRevision.revision_id == IndexPublication.revision_id)
                & (IndexRevision.document_version_id == clean.c.version_id),
            )
        )
    ).one()
    count, covered = int(counts[0]), int(counts[1])
    coverage = covered / count if count else None
    if coverage is not None:
        metric("mobius.indexer.coverage", coverage, "indexer")
    return {"cleanSources": count, "indexedCleanSources": covered, "indexCoverage": coverage}


def record_provider_observation(
    envelope: Mapping[str, Any],
    *,
    expected_resource_ids: frozenset[str],
    expected_release: str,
    expected_deployment: str,
    now: datetime | None = None,
) -> str:
    """Derive backup freshness/forecast from byte-bound native ARM readbacks.

    Caller retains native evidence privately and supplies deployment-authorized
    resources. Acceptance still requires independent evidence validation. Empty,
    failed, paginated, stale or incomplete responses emit no healthy value.
    """
    current = _aware(now or datetime.now(UTC))
    if set(envelope) != {
        "schema",
        "resourceId",
        "release",
        "deployment",
        "observedAt",
        "kind",
        "native",
        "nativeSha256",
    }:
        raise ValueError("provider observation fields differ")
    resource = envelope["resourceId"]
    if (
        envelope["schema"] != "mobius-provider-observation-v1"
        or resource not in expected_resource_ids
        or envelope["release"] != expected_release
        or envelope["deployment"] != expected_deployment
    ):
        raise ValueError("provider observation scope differs")
    observed = datetime.fromisoformat(str(envelope["observedAt"]).replace("Z", "+00:00"))
    if observed.tzinfo is None or not timedelta(0) <= current - observed <= timedelta(minutes=5):
        raise ValueError("provider observation is stale or future")
    raw = json.dumps(
        envelope["native"], sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != envelope["nativeSha256"]:
        raise ValueError("native provider response binding differs")
    native = envelope["native"]
    request, response = native["request"], native["response"]
    if response.get("status") != 200:
        raise ValueError("provider operation did not succeed")
    body = response["body"]
    if envelope["kind"] == "backup":
        if (
            request
            != {"method": "GET", "resourceId": resource + "/backups", "apiVersion": "2025-08-01"}
            or body.get("nextLink")
            or not isinstance(body.get("value"), list)
            or not 1 <= len(body["value"]) <= 1000
        ):
            raise ValueError("complete native backup list required")
        completed_times = []
        for row in body["value"]:
            if not str(row.get("id", "")).startswith(resource + "/backups/"):
                raise ValueError("backup resource outside approved server")
            completed = datetime.fromisoformat(
                str(row["properties"]["completedTime"]).replace("Z", "+00:00")
            )
            if completed.tzinfo is None or completed > observed:
                raise ValueError("provider backup completion invalid")
            completed_times.append(completed)
        value = (current - max(completed_times)).total_seconds()
        name, component = "mobius.backup.freshness", "backup"
    elif envelope["kind"] == "cost":
        if (
            request.get("method") != "POST"
            or request.get("resourceId")
            != resource + "/providers/Microsoft.CostManagement/forecast"
            or request.get("apiVersion") != "2025-03-01"
        ):
            raise ValueError("native forecast operation binding required")
        forecast = request.get("body", {})
        dataset = forecast.get("dataset", {})
        aggregations = dataset.get("aggregation", {})
        if (
            forecast.get("timeframe") != "Custom"
            or forecast.get("type") != "Usage"
            or forecast.get("includeActualCost") is not False
            or forecast.get("includeFreshPartialCost") is not False
            or set(dataset) != {"granularity", "aggregation"}
            or dataset["granularity"] != "Daily"
            or len(aggregations) != 1
            or next(iter(aggregations.values())) != {"name": "PreTaxCost", "function": "Sum"}
        ):
            raise ValueError("bound daily forecast-only request required")
        period = forecast.get("timePeriod", {})
        start = datetime.fromisoformat(str(period.get("from", "")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(period.get("to", "")).replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None or start > end:
            raise ValueError("forecast period invalid")
        first_day, last_day = start.astimezone(UTC).date(), end.astimezone(UTC).date()
        properties = body["properties"]
        columns = [item["name"] for item in properties["columns"]]
        rows = properties.get("rows")
        if (
            properties.get("nextLink")
            or not isinstance(rows, list)
            or not 1 <= len(rows) <= 1000
            or len(columns) != len(set(columns))
            or not {"PreTaxCost", "UsageDate", "CostStatus", "Currency"} <= set(columns)
        ):
            raise ValueError("complete native forecast rows required")
        value = 0.0
        dates = set()
        for row in rows:
            if len(row) != len(columns):
                raise ValueError("forecast row shape differs")
            data = dict(zip(columns, row, strict=True))
            usage = data["UsageDate"]
            if type(usage) is not int or len(str(usage)) != 8:
                raise ValueError("native forecast date invalid")
            day = datetime.strptime(str(usage), "%Y%m%d").date()
            if not first_day <= day <= last_day or day in dates:
                raise ValueError("forecast row outside bound period or duplicate daily total")
            dates.add(day)
            cost = data["PreTaxCost"]
            if (
                data["Currency"] != "USD"
                or data["CostStatus"] != "Forecast"
                or type(cost) not in (int, float)
                or not math.isfinite(cost)
                or cost < 0
            ):
                raise ValueError("native USD forecast required; posted charges are not forecast")
            value += cost
        name, component = "mobius.cost.estimated", "cost"
    else:
        raise ValueError("unsupported provider observation")
    metric(name, value, component)
    telemetry = current_telemetry()
    if telemetry is not None:
        telemetry.emit_log(
            event_name="dependency.state.changed",
            component=component,
            severity=Severity.INFO,
            fields={
                "operation": "native_provider_observation",
                "outcome": "success",
                "correlation_kind": "evidence",
                "correlation": telemetry.correlate(
                    "evidence",
                    envelope["nativeSha256"],
                    scope=(expected_release, expected_deployment),
                ),
            },
        )
    return name


def emit_document_boundary(document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    """Connect the committed API upload to worker spans through a real durable identity."""
    telemetry = current_telemetry()
    if telemetry is not None:
        span = telemetry.start_span(
            "domain_event.publish",
            component="event",
            links=(telemetry.span_link("document", document_id, scope=(workspace_id,)),),
            attributes={"operation": "committed_upload_request"},
        )
        span.end(outcome="success")
