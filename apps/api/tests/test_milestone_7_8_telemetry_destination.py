from __future__ import annotations

import copy
import json
import math
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts import telemetry_gateway
from scripts.telemetry_destination import AzureLogsDestination, DestinationError, destination_rows

SOURCE = {
    "service": "api",
    "environment": "staging",
    "release": "candidate-123",
    "deployment": "m78-isolated",
}


def payload() -> dict:
    return {
        "resource": {"schema": "mobius-operational-v1"},
        "signals": [
            {
                **SOURCE,
                "kind": "metric",
                "name": "mobius.queue.depth",
                "component": "queue",
                "timestamp": datetime.now(UTC).isoformat(),
                "schema_version": "mobius-operational-v1",
                "payload": {
                    "catalog_version": "mobius-signals-v1",
                    "type": "gauge",
                    "unit": "job",
                    "value": 0,
                    "labels": {"component": "queue", "outcome": "success"},
                },
            }
        ],
    }


def destination() -> AzureLogsDestination:
    return AzureLogsDestination(
        endpoint="https://fixture.eastus-1.ingest.monitor.azure.com",
        rule_id="dcr-" + "a" * 32,
        sources=[SOURCE],
        identity_endpoint="http://localhost:42356/msi/token",
        identity_header="synthetic-header",
        client_id="12345678-1234-1234-1234-123456789012",
    )


async def test_gateway_destination_uses_identity_and_actual_ingestion_ack() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "localhost":
            assert request.url.params["resource"] == "https://monitor.azure.com/"
            assert request.headers["X-IDENTITY-HEADER"] == "synthetic-header"
            return httpx.Response(200, json={"access_token": "synthetic-token"})
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        rows = json.loads(request.content)
        assert rows[0]["Payload"]["value"] == 0
        assert rows[0]["Deployment"] == "m78-isolated"
        assert len(rows[0]["SignalId"]) == 64
        return httpx.Response(204)

    await destination().export(payload(), transport=httpx.MockTransport(respond))
    assert len(requests) == 2


@pytest.mark.parametrize("value", [
    0.007600000003549212, 0.006401000064215623, 0.020700000050055678,
    math.ulp(0.0), math.nextafter(2.0**52, 0.0),
])
async def test_fractional_metric_survives_ingestion_with_its_gateway_identity(value):
    from infra.milestone_7_8.destination_acceptance import validate_signal_row

    batch = payload()
    signal = batch["signals"][0]
    signal["payload"]["value"] = value
    logical, = destination_rows(batch, [SOURCE])
    sent = []

    def reply(request):
        if request.url.host == "localhost":
            return httpx.Response(200, json={"access_token": "synthetic-token"})
        sent.extend(json.loads(request.content))
        return httpx.Response(204)

    await destination().export(batch, transport=httpx.MockTransport(reply))
    wire, = sent
    assert wire["Payload"] == logical["Payload"] | {"value": repr(value), "value_encoding": "binary64-decimal-v1"}
    assert wire["SignalId"] == logical["SignalId"]
    native = wire | {"NativePayloadType": "dictionary", "NativeMetricValueType": "string",
                     "NativeMetricExponent": None, "NativeMetricSignificand": None}
    stamp = datetime.fromisoformat(signal["timestamp"])
    assert validate_signal_row(native, [SOURCE], stamp, set()) == signal
    for changed in (
        logical["Payload"] | {"value": repr(value)},
        wire["Payload"] | {"value": repr(math.nextafter(value, 0.0))},
        wire["Payload"] | {"value": " " + repr(value)},
        wire["Payload"] | {"value_encoding": "unknown"},
    ):
        with pytest.raises(ValueError):
            validate_signal_row(native | {"Payload": changed}, [SOURCE], stamp, set())

    signal["payload"] = wire["Payload"]
    with pytest.raises(DestinationError, match="invalid_operational_signal"):
        await destination().export(batch, transport=httpx.MockTransport(reply))
    assert len(sent) == 1


@pytest.mark.parametrize("status", [200, 202, 301, 401, 403, 429, 500])
async def test_destination_failure_does_not_ack_or_retry(status: int) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return (
            httpx.Response(200, json={"access_token": "secret"})
            if request.url.host == "localhost"
            else httpx.Response(status, text="private provider response")
        )

    with pytest.raises(DestinationError, match=r"^telemetry_destination_unavailable$"):
        await destination().export(payload(), transport=httpx.MockTransport(respond))
    assert len(requests) == 2


@pytest.mark.parametrize("mutation", ["source", "content", "metric", "future", "nonfinite"])
async def test_invalid_signal_never_requests_token(mutation: str) -> None:
    value = payload()
    signal = value["signals"][0]
    if mutation == "source":
        signal["release"] = "another-release"
    elif mutation == "content":
        signal["payload"]["prompt"] = "private content"
    elif mutation == "metric":
        signal["name"] = "unregistered.metric"
    elif mutation == "future":
        signal["timestamp"] = "2099-01-01T00:00:00Z"
    else:
        signal["payload"]["value"] = float("inf")

    def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("Unsafe input reached identity/destination")

    with pytest.raises(DestinationError, match="invalid_operational_signal"):
        await destination().export(value, transport=httpx.MockTransport(forbidden))


def test_identical_retry_has_same_id_and_different_payload_does_not() -> None:
    value = payload()
    first = destination_rows(value, [SOURCE])
    assert destination_rows(value, [SOURCE]) == first
    changed = copy.deepcopy(value)
    changed["signals"][0]["payload"]["value"] = 1
    assert destination_rows(changed, [SOURCE])[0]["SignalId"] != first[0]["SignalId"]


def test_gateway_propagates_sink_failure_without_private_body(monkeypatch) -> None:
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_GATEWAY_TOKEN", "synthetic-token-" * 4)

    class Unavailable:
        async def export(self, _: object) -> None:
            raise DestinationError("telemetry_destination_unavailable")

    monkeypatch.setattr(telemetry_gateway, "_destination", lambda: Unavailable())
    with TestClient(telemetry_gateway.application) as client:
        result = client.post(
            "/v1/signals",
            json=payload(),
            headers={
                "Authorization": "Bearer " + "synthetic-token-" * 4,
            },
        )
    assert result.status_code == 503
    assert result.json() == {"detail": "destination_unavailable"}


def test_gateway_stream_body_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_GATEWAY_TOKEN", "synthetic-token-" * 4)
    with TestClient(telemetry_gateway.application) as client:
        result = client.post(
            "/v1/signals",
            content=b"x" * (512 * 1024 + 1),
            headers={
                "Authorization": "Bearer " + "synthetic-token-" * 4,
            },
        )
    assert result.status_code == 413


def test_unconfigured_destination_does_not_fall_back_to_hash_ack(monkeypatch) -> None:
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_GATEWAY_TOKEN", "synthetic-token-" * 4)
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_GATEWAY_DESTINATION", "azure_logs")
    monkeypatch.delenv("OPENCANVAS_TELEMETRY_DCE_ENDPOINT", raising=False)
    with TestClient(telemetry_gateway.application) as client:
        assert client.get("/health").status_code == 503
        result = client.post(
            "/v1/signals",
            json=payload(),
            headers={
                "Authorization": "Bearer " + "synthetic-token-" * 4,
            },
        )
    assert result.status_code == 503
