from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from opencanvas_api.core.config import get_settings
from opencanvas_api.main import create_app


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
        "version": "0.1.0",
        "environment": get_settings().environment,
        "ai_provider": None,
        "ai_configured": None,
    }


async def test_readiness_reports_mock_provider_without_secret(
    health_client: httpx.AsyncClient,
) -> None:
    response = await health_client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["ai_provider"] == "mock"
    assert response.json()["ai_configured"] is False


async def test_api_responses_include_security_headers(health_client: httpx.AsyncClient) -> None:
    response = await health_client.get("/api/v1/health/live")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["permissions-policy"] == "camera=(), geolocation=(), microphone=()"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
