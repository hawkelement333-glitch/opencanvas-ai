"""Read-only, bounded integrity observations over existing evidence tables.

Baselines and row identities are private operator evidence, never telemetry.
A first sample cannot prove absence of append-only mutation. A truncated sample
is rejected rather than represented as a healthy zero.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import Base
from opencanvas_api.services.observability import Severity
from opencanvas_api.services.operational_observations import current_telemetry, metric

TRANSITIONS = {
    "storage_object_lifecycle_transitions": "object_version_id",
    "upload_session_transitions": "session_id",
    "ingestion_request_transitions": "request_id",
}
BASE_TABLES = (
    "domain_events",
    "domain_event_outbox",
    "domain_event_provenance",
    "domain_activity_entries",
    "trace_events",
    "trace_evidence_bundles",
    "durable_job_requests",
    "durable_job_outcomes",
    "document_processing_jobs",
    *TRANSITIONS,
)
AUDIT_IDENTITIES = {
    "collaboration_audit_events": "audit_event_id",
    "durable_job_audit_events": "audit_event_id",
    "indexer_audit_events": "audit_event_id",
    "object_ingestion_audit_events": "audit_event_id",
    "controlled_agent_audit_events": "event_id",
}
AUDIT_TABLES = tuple(AUDIT_IDENTITIES)
TABLES = (*BASE_TABLES, *AUDIT_TABLES)
MUTABLE = {"domain_event_outbox", "document_processing_jobs"}


def _canonical(value: object) -> bytes:
    def scalar(item: object) -> str:
        if isinstance(item, bytes):
            return "sha256:" + hashlib.sha256(item).hexdigest()
        return str(item)

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=scalar).encode()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def observe_evidence_integrity(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    previous: Mapping[str, Any] | None = None,
    row_limit: int = 256,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 1 <= row_limit <= 2048:
        raise ValueError("integrity row bound exceeds contract")
    rows = {}
    for name in TABLES:
        table = Base.metadata.tables[name]
        found = list(
            (
                await session.execute(
                    select(table)
                    .where(
                        table.c.workspace_id == workspace_id,
                    )
                    .limit(row_limit + 1)
                )
            ).mappings()
        )
        if len(found) > row_limit:
            raise ValueError("integrity sample truncated; acceptance unknown")
        rows[name] = [dict(row) for row in found]
    telemetry = current_telemetry()
    dropped = (
        (telemetry.counters.dropped + telemetry.counters.export_failures) if telemetry else None
    )
    result = assess_evidence_rows(
        rows, workspace_id, previous=previous, now=now, telemetry_gaps=dropped
    )
    total = sum(result["findings"].values())
    if total or not result["unknown"]:
        metric("mobius.evidence.integrity", total, "audit", "server_error" if total else "success")
    if telemetry:
        telemetry.emit_log(
            event_name="integrity.check.completed",
            component="audit",
            severity=Severity.ERROR if total else Severity.INFO,
            fields={
                "operation": "bounded_evidence_integrity",
                "count": total,
                "outcome": "server_error" if total else "other" if result["unknown"] else "success",
            },
        )
    return result


def assess_evidence_rows(
    rows: Mapping[str, list[dict[str, Any]]],
    workspace_id: uuid.UUID,
    *,
    previous: Mapping[str, Any] | None,
    now: datetime | None = None,
    telemetry_gaps: int | None,
) -> dict[str, Any]:
    if set(rows) != set(TABLES):
        raise ValueError("complete integrity table inventory required")
    if any(
        str(row["workspace_id"]) != str(workspace_id) for table in rows.values() for row in table
    ):
        raise ValueError("integrity sample scope mismatch")
    current = _aware(now or datetime.now(UTC))
    findings = {
        name: 0
        for name in [
            "audit_sequence_gaps",
            "trace_parent_gaps",
            "event_outbox_orphans",
            "evidence_link_orphans",
            "impossible_transitions",
            "stale_backlog",
            "duplicate_durable_identities",
            "append_only_mutations",
            "telemetry_gaps",
        ]
    }
    unknown = []
    event_rows = rows["domain_events"]
    event_ids = {str(row["event_id"]) for row in event_rows}
    outbox_ids = {str(row["event_id"]) for row in rows["domain_event_outbox"]}
    findings["event_outbox_orphans"] = len(event_ids ^ outbox_ids)
    sequences = sorted({int(row["sequence"]) for row in event_rows})
    if sequences:
        findings["audit_sequence_gaps"] += max(sequences) - len(sequences)
    traces = {str(row["trace_id"]) for row in rows["trace_events"]}
    findings["trace_parent_gaps"] = sum(
        row.get("parent_trace_id") is not None and str(row["parent_trace_id"]) not in traces
        for row in rows["trace_events"]
    )
    audit_ids = {str(row[AUDIT_IDENTITIES[name]]) for name in AUDIT_TABLES for row in rows[name]}
    for name in [
        "domain_events",
        "domain_event_provenance",
        "domain_activity_entries",
        "trace_evidence_bundles",
    ]:
        for row in rows[name]:
            if row.get("event_id") is not None and str(row["event_id"]) not in event_ids:
                findings["evidence_link_orphans"] += 1
            if row.get("trace_id") is not None and str(row["trace_id"]) not in traces:
                findings["evidence_link_orphans"] += 1
            if (
                row.get("audit_event_id") is not None
                and str(row["audit_event_id"]) not in audit_ids
            ):
                findings["evidence_link_orphans"] += 1
    for row in rows["trace_evidence_bundles"]:
        if row["state"] == "completed":
            content = row["artifact_bytes"]
            if (
                not isinstance(content, bytes)
                or len(content) != row["byte_size"]
                or hashlib.sha256(content).hexdigest() != row["artifact_sha256"]
            ):
                findings["evidence_link_orphans"] += 1
    for table, identity in TRANSITIONS.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows[table]:
            grouped[str(row[identity])].append(row)
        for transitions in grouped.values():
            ordered = sorted(transitions, key=lambda r: r["sequence"])
            if ordered[0]["sequence"] != 0:
                findings["audit_sequence_gaps"] += 1
            if ordered[0]["previous_state"] is not None:
                findings["impossible_transitions"] += 1
            for before, after in pairwise(ordered):
                if after["sequence"] != before["sequence"] + 1:
                    findings["audit_sequence_gaps"] += 1
                if after["previous_state"] != before["current_state"]:
                    findings["impossible_transitions"] += 1
    for row in rows["domain_event_outbox"]:
        if row["delivery_state"] in {"pending", "retry_wait", "delivering"}:
            findings["stale_backlog"] += int(
                (current - _aware(row["created_at"])).total_seconds() >= 300
            )
    for name, fields in [
        ("domain_events", ("user_id", "scope_id", "event_type", "source_identity")),
        ("domain_event_outbox", ("event_id",)),
        ("durable_job_outcomes", ("job_run_id",)),
    ]:
        counts = Counter(tuple(str(row[field]) for field in fields) for row in rows[name])
        findings["duplicate_durable_identities"] += sum(count - 1 for count in counts.values())
    hashes = {}
    for name in TABLES:
        if name in MUTABLE:
            continue
        source_table = Base.metadata.tables[name]
        hashes[name] = {
            "|".join(
                str(row[col.name]) for col in source_table.primary_key.columns
            ): hashlib.sha256(_canonical(row)).hexdigest()
            for row in rows[name]
        }
    if previous is None:
        unknown.append("append_only_mutations")
    else:
        if previous.get("workspaceId") != str(workspace_id) or set(
            previous.get("immutableRows", {})
        ) != set(hashes):
            raise ValueError("integrity baseline scope/inventory mismatch")
        for name, records in previous["immutableRows"].items():
            findings["append_only_mutations"] += sum(
                hashes[name].get(key) != value for key, value in records.items()
            )
    if telemetry_gaps is None:
        unknown.append("telemetry_gaps")
    elif type(telemetry_gaps) is not int or telemetry_gaps < 0:
        raise ValueError("actual telemetry counters required")
    else:
        findings["telemetry_gaps"] = telemetry_gaps
    return {
        "schema": "mobius-integrity-observation-v1",
        "workspaceId": str(workspace_id),
        "observedAt": current.isoformat(),
        "findings": findings,
        "unknown": unknown,
        "immutableRows": hashes,
        "repairPerformed": False,
        "investigationClosure": "not-authorized",
    }
