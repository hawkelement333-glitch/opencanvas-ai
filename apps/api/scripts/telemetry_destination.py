"""Private Azure Logs Ingestion adapter for the existing bounded gateway.

No fallback sink, destination retry, raw payload logging or query permission.
The caller receives success only after the configured DCR accepted the batch.
Azure ingestion is at-least-once; queries deduplicate the stable SignalId.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from opencanvas_api.services.observability import (
    _COMPONENTS,
    _OUTCOMES,
    ALLOWED_EVENT_NAMES,
    ALLOWED_SPAN_NAMES,
    LOG_FIELD_LIMITS,
    METRIC_CATALOG,
    SCHEMA_VERSION,
    SIGNAL_CATALOG_VERSION,
    SPAN_ATTRIBUTE_LIMITS,
    Severity,
    _redact,
)

SOURCE_FIELDS = ("service", "environment", "release", "deployment")
SIGNAL_FIELDS = frozenset(
    ("kind", "name", "timestamp", "component", "payload", "schema_version", *SOURCE_FIELDS)
)
KINDS = frozenset(("application_log", "security_log", "metric", "span"))
_SAFE_IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}\Z")


class DestinationError(Exception):
    """Safe code only; provider response bodies and tokens never escape."""


def _require(condition: bool) -> None:
    if not condition:
        raise DestinationError("invalid_operational_signal")


def _safe_fields(value: object, limits: Mapping[str, int]) -> None:
    _require(isinstance(value, dict))
    assert isinstance(value, dict)
    _require(set(value) <= set(limits))
    for key, item in value.items():
        _require(isinstance(item, str) and item == _redact(item, limit=limits[key]))


def _hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{length}}}", value) is not None


def _finite(value: object) -> bool:
    return (
        isinstance(value, (float, int))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _validate_signal(signal: object, sources: list[dict[str, str]], now: datetime) -> None:
    _require(isinstance(signal, dict))
    assert isinstance(signal, dict)
    _require(set(signal) == SIGNAL_FIELDS and signal["schema_version"] == SCHEMA_VERSION)
    _require({key: signal[key] for key in SOURCE_FIELDS} in sources)
    kind, name, payload = signal["kind"], signal["name"], signal["payload"]
    _require(kind in KINDS and signal["component"] in _COMPONENTS)
    _require(isinstance(name, str) and isinstance(payload, dict))
    _require(isinstance(signal["timestamp"], str))
    try:
        timestamp = datetime.fromisoformat(signal["timestamp"].replace("Z", "+00:00"))
        _require(timestamp.tzinfo is not None)
        _require(now - timedelta(minutes=15) <= timestamp <= now + timedelta(minutes=5))
    except (ValueError, TypeError) as exc:
        raise DestinationError("invalid_operational_signal") from exc
    if kind in ("application_log", "security_log"):
        _require(name in ALLOWED_EVENT_NAMES)
        _require(payload.get("severity") in {item.value for item in Severity})
        _safe_fields(
            {
                key: item
                for key, item in payload.items()
                if key not in {"severity", "trace_id", "span_id"}
            },
            LOG_FIELD_LIMITS,
        )
        _require(("trace_id" in payload) == ("span_id" in payload))
        if "trace_id" in payload:
            _require(_hex(payload["trace_id"], 32) and _hex(payload["span_id"], 16))
    elif kind == "metric":
        definition = METRIC_CATALOG.get(name)
        _require(definition is not None)
        assert definition is not None
        _require(set(payload) == {"catalog_version", "type", "unit", "value", "labels"})
        _require(payload["catalog_version"] == SIGNAL_CATALOG_VERSION)
        _require(payload["type"] == definition.metric_type.value)
        _require(payload["unit"] == definition.unit and _finite(payload["value"]))
        labels = payload["labels"]
        _require(isinstance(labels, dict) and set(labels) == set(definition.allowed_labels))
        _require(all(value in definition.allowed_labels[key] for key, value in labels.items()))
    else:
        _require(name in ALLOWED_SPAN_NAMES)
        expected = {
            "trace_id",
            "span_id",
            "depth",
            "duration_ms",
            "outcome",
            "attributes",
            "events",
            "links",
        }
        _require(set(payload) in (expected, expected | {"failure_class"}))
        _require(_hex(payload["trace_id"], 32) and _hex(payload["span_id"], 16))
        _require(type(payload["depth"]) is int and 0 <= payload["depth"] <= 16)
        _require(_finite(payload["duration_ms"]) and payload["outcome"] in _OUTCOMES)
        _safe_fields(payload["attributes"], SPAN_ATTRIBUTE_LIMITS)
        if "failure_class" in payload:
            _safe_fields({"failure_class": payload["failure_class"]}, LOG_FIELD_LIMITS)
        events, links = payload["events"], payload["links"]
        _require(isinstance(events, list) and len(events) <= 16)
        _require(isinstance(links, list) and len(links) <= 8)
        for event in events:
            _require(isinstance(event, dict) and "name" in event)
            _require(
                isinstance(event["name"], str)
                and re.fullmatch(r"[a-z][a-z0-9_.-]{0,95}", event["name"]) is not None
            )
            _safe_fields(
                {key: value for key, value in event.items() if key != "name"}, SPAN_ATTRIBUTE_LIMITS
            )
        for link in links:
            _require(isinstance(link, dict) and set(link) == {"trace_id", "span_id", "correlation"})
            _require(_hex(link["trace_id"], 32) and _hex(link["span_id"], 16))
            _require(link["correlation"] is None or _hex(link["correlation"], 20))


def destination_rows(
    payload: object, sources: list[dict[str, str]], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Reject unsafe or unbound input before requesting an identity token."""
    _require(isinstance(payload, dict) and set(payload) == {"resource", "signals"})
    assert isinstance(payload, dict)
    _require(payload["resource"] == {"schema": SCHEMA_VERSION})
    signals = payload["signals"]
    _require(isinstance(signals, list) and 1 <= len(signals) <= 512)
    rows = []
    current = now or datetime.now(UTC)
    for signal in signals:
        try:
            _validate_signal(signal, sources, current)
        except (KeyError, TypeError, AttributeError) as exc:
            raise DestinationError("invalid_operational_signal") from exc
        canonical = json.dumps(signal, sort_keys=True, separators=(",", ":"), allow_nan=False)
        rows.append(
            {
                "TimeGenerated": signal["timestamp"],
                "SignalId": hashlib.sha256(canonical.encode()).hexdigest(),
                "Kind": signal["kind"],
                "Name": signal["name"],
                "Service": signal["service"],
                "Environment": signal["environment"],
                "Release": signal["release"],
                "Deployment": signal["deployment"],
                "Component": signal["component"],
                "Payload": signal["payload"],
            }
        )
    return rows


class AzureLogsDestination:
    def __init__(
        self,
        *,
        endpoint: str,
        rule_id: str,
        sources: list[dict[str, str]],
        identity_endpoint: str,
        identity_header: str,
        client_id: str,
    ) -> None:
        parsed = urlparse(endpoint)
        _require(
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.endswith(".ingest.monitor.azure.com")
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and not parsed.username
            and parsed.port in (None, 443)
        )
        _require(re.fullmatch(r"dcr-[a-f0-9]{32}", rule_id) is not None)
        identity = urlparse(identity_endpoint)
        _require(
            identity.scheme == "http"
            and identity.hostname in {"localhost", "127.0.0.1", "169.254.169.254"}
            and not identity.username
            and not identity.fragment
            and not identity.query
        )
        _require(bool(identity_header) and re.fullmatch(r"[a-fA-F0-9-]{36}", client_id) is not None)
        _require(1 <= len(sources) <= 8)
        for source in sources:
            _require(set(source) == set(SOURCE_FIELDS))
            _require(
                all(
                    isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value) is not None
                    for value in source.values()
                )
            )
        self.url = (
            f"{endpoint.rstrip('/')}/dataCollectionRules/{rule_id}"
            "/streams/Custom-MobiusOperational?api-version=2023-01-01"
        )
        self.sources = sources
        self.identity_endpoint = identity_endpoint
        self.identity_header = identity_header
        self.client_id = client_id

    @classmethod
    def from_environment(cls) -> AzureLogsDestination:
        try:
            return cls(
                endpoint=os.environ["OPENCANVAS_TELEMETRY_DCE_ENDPOINT"],
                rule_id=os.environ["OPENCANVAS_TELEMETRY_DCR_IMMUTABLE_ID"],
                sources=json.loads(os.environ["OPENCANVAS_TELEMETRY_GATEWAY_SOURCES_JSON"]),
                identity_endpoint=os.environ["IDENTITY_ENDPOINT"],
                identity_header=os.environ["IDENTITY_HEADER"],
                client_id=os.environ["AZURE_CLIENT_ID"],
            )
        except (KeyError, ValueError, TypeError, DestinationError) as exc:
            raise DestinationError("telemetry_destination_not_configured") from exc

    async def export(
        self, payload: object, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        rows = destination_rows(payload, self.sources)
        try:
            # One dispatch only. Upstream owns bounded retries; stable IDs permit
            # query-side deduplication after an ambiguous ingestion response.
            async with (
                asyncio.timeout(4.5),
                httpx.AsyncClient(
                    timeout=2.0,
                    follow_redirects=False,
                    transport=transport,
                    trust_env=False,
                ) as client,
            ):
                identity = await client.get(
                    self.identity_endpoint,
                    params={
                        "api-version": "2019-08-01",
                        "resource": "https://monitor.azure.com/",
                        "client_id": self.client_id,
                    },
                    headers={"X-IDENTITY-HEADER": self.identity_header},
                )
                identity.raise_for_status()
                token = identity.json().get("access_token")
                if not isinstance(token, str) or not token:
                    raise DestinationError("telemetry_identity_unavailable")
                result = await client.post(
                    self.url, json=rows, headers={"Authorization": f"Bearer {token}"}
                )
                if result.status_code != 204:
                    raise DestinationError("telemetry_destination_unavailable")
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            raise DestinationError("telemetry_destination_unavailable") from exc
