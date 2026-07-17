from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import get_database, get_session
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import Base
from opencanvas_api.db.session import Database
from opencanvas_api.main import create_app


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def app(database: Database, tmp_path: Path) -> FastAPI:
    application = create_app()
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        ai_context_character_limit=10_000,
        document_storage_root=tmp_path / "documents",
        embedding_provider="mock",
    )

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with database.sessions() as session:
            yield session

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_database] = lambda: database
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


@pytest.fixture
def api_prefix() -> str:
    return "/api/v1"
