import asyncio
import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from structlog.testing import capture_logs

from opencanvas_api.core.config import get_settings
from opencanvas_api.db.runtime import DatabaseRuntimeError
from opencanvas_api.main import create_app
from opencanvas_api.services.observability import (
    HttpTelemetrySink,
    InMemoryTelemetrySink,
    OperationalTelemetry,
)


@pytest.fixture(autouse=True)
def in_memory_health_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("OPENCANVAS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def health_client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_liveness_is_dependency_free(health_client: httpx.AsyncClient) -> None:
    response = await health_client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "opencanvas-api",
    }


async def test_readiness_is_minimal_and_does_not_disclose_dependencies(
    health_client: httpx.AsyncClient,
) -> None:
    response = await health_client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "opencanvas-api"}


async def test_api_responses_include_security_headers(health_client: httpx.AsyncClient) -> None:
    response = await health_client.get("/api/v1/health/live")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["permissions-policy"] == "camera=(), geolocation=(), microphone=()"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


async def test_readiness_recovers_after_a_temporary_database_failure(
    health_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opencanvas_api.api.routes import health

    calls = 0

    async def transient_probe(*args: object, **kwargs: object) -> object:
        nonlocal calls
        del args, kwargs
        calls += 1
        if calls == 1:
            raise DatabaseRuntimeError("database_unavailable")
        return object()

    monkeypatch.setattr(health, "validate_database_runtime", transient_probe)

    unavailable = await health_client.get("/api/v1/health/ready")
    recovered = await health_client.get("/api/v1/health/ready")
    live = await health_client.get("/api/v1/health/live")

    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "service_not_ready"
    assert "database" not in unavailable.text
    assert recovered.status_code == 200
    assert live.status_code == 200


async def test_operator_health_is_server_allowlisted_and_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_user = "00000000-0000-4000-8000-000000000001"
    monkeypatch.setenv("OPENCANVAS_AUTH_ENABLED", "false")
    monkeypatch.setenv("OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS", f'["{system_user}"]')
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_EXPORTER", "memory")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET", "o" * 48)
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health/operator")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "healthy"
            assert set(body["dependencies"]) == {
                "database",
                "storage",
                "limiter",
                "worker",
                "telemetry",
            }
            assert "url" not in response.text.lower()
            assert "credential" not in response.text.lower()
            telemetry = app.state.observability
            assert isinstance(telemetry, OperationalTelemetry)
            assert isinstance(telemetry._sink, InMemoryTelemetrySink)
    get_settings.cache_clear()


async def test_operator_health_denies_unlisted_authenticated_user_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCANVAS_AUTH_ENABLED", "false")
    monkeypatch.setenv("OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS", "[]")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health/operator")
    assert response.status_code == 404
    assert response.json()["code"] == "health_not_found"
    get_settings.cache_clear()


async def test_request_telemetry_uses_server_derived_correlation_and_safe_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.telemetry_destination import destination_rows

    from opencanvas_api import main

    monkeypatch.setattr(main, "API_TELEMETRY_FLUSH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_EXPORTER", "http")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_ENDPOINT", "https://gateway.invalid/v1/signals")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_SERVICE_NAME", "mobius-api")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET", "o" * 48)
    get_settings.cache_clear()
    app = create_app()
    telemetry: OperationalTelemetry = app.state.observability
    sink = telemetry._sink
    assert isinstance(sink, HttpTelemetrySink)
    await sink.close()
    native_rows: list[dict] = []
    delivered = asyncio.Event()
    gateway_statuses = iter((503, 202))
    settings = get_settings()
    sources = [
        {
            "service": "mobius-api",
            "environment": settings.runtime_mode.value,
            "release": settings.telemetry_release,
            "deployment": settings.telemetry_deployment,
        }
    ]

    def gateway(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://gateway.invalid/v1/signals"
        status = next(gateway_statuses)
        rows = destination_rows(json.loads(request.content), sources)
        if status == 202:
            native_rows.extend(rows)
            delivered.set()
        return httpx.Response(status)

    sink._client = httpx.AsyncClient(transport=httpx.MockTransport(gateway))
    with capture_logs() as logs:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/health/live?token=private",
                    headers={"X-Request-ID": "client-controlled", "traceparent": "invalid"},
                )
                assert response.status_code == 200
                assert response.headers["X-Request-ID"] != "client-controlled"
                assert response.headers["traceparent"].startswith("00-")
            assert settings.telemetry_batch_size == 64
            await asyncio.wait_for(delivered.wait(), timeout=1)
            assert {
                "api.request.completed",
                "mobius.api.requests",
                "mobius.api.duration",
            } <= {row["Name"] for row in native_rows}
            completed = next(row for row in native_rows if row["Name"] == "api.request.completed")
            assert completed["Payload"]["route"] == "/health/live"
            trace_id = response.headers["traceparent"].split("-")[1]
            assert completed["Payload"]["trace_id"] == trace_id
            assert [log for log in logs if log["event"] == "telemetry_liveness_delivery"] == [
                {
                    "event": "telemetry_liveness_delivery",
                    "log_level": "info",
                    "trace_id": trace_id,
                    "gateway_status": status,
                }
                for status in (503, 202)
            ]
            serialized = json.dumps(native_rows)
            assert "private" not in serialized
            assert "client-controlled" not in serialized
    get_settings.cache_clear()
