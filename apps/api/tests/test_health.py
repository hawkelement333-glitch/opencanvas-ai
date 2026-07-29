from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from opencanvas_api.core.config import get_settings
from opencanvas_api.db.runtime import DatabaseRuntimeError
from opencanvas_api.main import create_app
from opencanvas_api.services.observability import InMemoryTelemetrySink, OperationalTelemetry


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
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_EXPORTER", "memory")
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET", "o" * 48)
    get_settings.cache_clear()
    app = create_app()
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
        telemetry: OperationalTelemetry = app.state.observability
        await telemetry.flush()
        sink = telemetry._sink
        assert isinstance(sink, InMemoryTelemetrySink)
        serialized = str([signal.as_dict() for signal in sink.signals])
        assert "private" not in serialized
        assert "client-controlled" not in serialized
        assert "/health/live" in serialized
    get_settings.cache_clear()
