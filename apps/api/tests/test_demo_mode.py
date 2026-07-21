from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.demo import (
    build_demo_environment,
    build_web_command,
    validate_demo_environment,
    validate_reset_target,
)
from sqlalchemy import func, select

from opencanvas_api.core.config import (
    DEMO_DATABASE_URL,
    DEMO_DOCUMENT_STORAGE_ROOT,
    Settings,
    get_settings,
)
from opencanvas_api.db.models import (
    AIExecutionChunk,
    AIRequest,
    AIResponse,
    AIResponseSource,
    Canvas,
    Citation,
    Document,
    TraceEvent,
)
from opencanvas_api.services.demo import (
    DEMO_CANVAS_ID,
    DEMO_INSUFFICIENT_RESPONSE_ID,
    DEMO_REQUEST_ID,
    DEMO_TRACE_ID,
    seed_demo,
    validate_demo_seed,
)


def demo_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "development",
        "demo_mode": True,
        "database_url": DEMO_DATABASE_URL,
        "ai_provider": "mock",
        "embedding_provider": "mock",
        "document_storage_root": DEMO_DOCUMENT_STORAGE_ROOT,
        "openai_api_key": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"environment": "production"}, "production environment"),
        ({"database_url": "postgresql+asyncpg://prod.example/app"}, "demo database"),
        ({"openai_api_key": "not-a-real-key"}, "refuses OpenAI credentials"),
        ({"ai_provider": "openai"}, "requires mock AI"),
        ({"embedding_provider": "openai"}, "requires mock AI"),
        ({"document_storage_root": Path("./data/documents")}, "document store"),
    ],
)
def test_demo_settings_reject_unsafe_configuration(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        demo_settings(**override)


def test_demo_startup_environment_strips_credentials_and_uses_isolated_paths() -> None:
    environment = build_demo_environment(
        {
            "OPENAI_API_KEY": "must-not-survive",
            "OPENCANVAS_OPENAI_API_KEY": "must-not-survive-either",
            "OPENCANVAS_DATABASE_URL": "postgresql+asyncpg://production.example/app",
        }
    )

    settings = validate_demo_environment(environment)

    assert environment["OPENAI_API_KEY"] == ""
    assert environment["OPENCANVAS_OPENAI_API_KEY"] == ""
    assert settings.database_url == DEMO_DATABASE_URL
    assert settings.document_storage_root == DEMO_DOCUMENT_STORAGE_ROOT
    assert settings.effective_ai_provider == "mock"
    assert settings.effective_embedding_provider == "mock"
    assert build_web_command("corepack") == [
        "corepack",
        "pnpm",
        "--filter",
        "@opencanvas/web",
        "dev",
    ]


def test_demo_reset_accepts_only_the_exact_project_local_runtime(tmp_path: Path) -> None:
    safe_target = tmp_path / ".runtime" / "demo"
    validate_reset_target(safe_target, tmp_path)

    with pytest.raises(RuntimeError, match="unexpected demo runtime path"):
        validate_reset_target(tmp_path, tmp_path)
    with pytest.raises(RuntimeError, match="unexpected demo runtime path"):
        validate_reset_target(tmp_path / "data" / "documents", tmp_path)


async def test_demo_seed_is_idempotent_and_persists_a_complete_evidence_story(
    database, tmp_path: Path
) -> None:
    async with database.sessions() as session:
        first = await seed_demo(session, tmp_path / "demo-documents")
        second = await seed_demo(session, tmp_path / "demo-documents")

        assert first.created is True
        assert second.created is False
        assert first.canvas_id == DEMO_CANVAS_ID
        assert first.trace_id == DEMO_TRACE_ID
        assert await session.scalar(select(func.count()).select_from(Canvas)) == 1
        assert await session.scalar(select(func.count()).select_from(Document)) == 2
        assert await session.scalar(select(func.count()).select_from(Citation)) == 2
        assert await session.scalar(select(func.count()).select_from(AIResponseSource)) == 2
        assert await session.scalar(select(func.count()).select_from(TraceEvent)) == 4

        request = await session.get(AIRequest, DEMO_REQUEST_ID)
        assert request is not None
        assert request.provider == "mock"
        assert request.model_configuration["mode"] == "replay"
        assert request.model_configuration["externalCall"] is False
        assert len(request.selected_node_ids) == 3

        response = await session.scalar(
            select(AIResponse).where(AIResponse.request_id == DEMO_REQUEST_ID)
        )
        assert response is not None
        assert response.grounded is True
        assert response.provider_response_id is None
        assert response.input_tokens is None
        assert "DETERMINISTIC REPLAY" in response.content
        assert "Supported:" in response.content
        assert "Inference:" in response.content
        assert "Conflict:" in response.content
        assert "Unsupported:" in response.content

        insufficient = await session.get(AIResponse, DEMO_INSUFFICIENT_RESPONSE_ID)
        assert insufficient is not None
        assert insufficient.grounded is False
        assert insufficient.insufficient_evidence is True
        assert insufficient.provider_response_id is None
        assert "Insufficient evidence:" in insufficient.content
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Citation)
                .where(Citation.ai_response_id == DEMO_INSUFFICIENT_RESPONSE_ID)
            )
            == 0
        )

        ranked = (
            await session.scalars(
                select(AIExecutionChunk)
                .where(AIExecutionChunk.request_id == DEMO_REQUEST_ID)
                .order_by(AIExecutionChunk.rank)
            )
        ).all()
        assert [chunk.rank for chunk in ranked] == [1, 2]
        assert all(chunk.included_in_context for chunk in ranked)
        await validate_demo_seed(session, tmp_path / "demo-documents")

    assert (tmp_path / "demo-documents" / f"{first.canvas_id.hex}").exists() is False
    assert list((tmp_path / "demo-documents").rglob("*.md"))


async def test_runtime_endpoint_distinguishes_replay_from_live_mode(client, app) -> None:
    settings = demo_settings()
    # The production safety validator intentionally rejects a non-isolated database; the endpoint
    # receives an already validated test double so it can exercise only the response contract.
    object.__setattr__(settings, "database_url", "sqlite+aiosqlite:///:memory:")
    app.dependency_overrides[get_settings] = lambda: settings

    response = await client.get("/api/v1/health/runtime")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "deterministic_replay",
        "appMode": "demo",
        "externalAiEnabled": False,
        "label": "Build Week demo · deterministic replay · no external AI calls",
        "demoCanvasId": str(DEMO_CANVAS_ID),
        "demoTraceId": str(DEMO_TRACE_ID),
    }
