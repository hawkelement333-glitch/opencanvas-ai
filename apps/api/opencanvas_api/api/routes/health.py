import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api import __version__
from opencanvas_api.api.dependencies import get_session
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import WorkerHeartbeat
from opencanvas_api.services.demo import DEMO_CANVAS_ID, DEMO_TRACE_ID
from opencanvas_api.services.documents import DocumentServiceError, build_document_storage

router = APIRouter(prefix="/health")
SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
    service: str
    version: str
    environment: str
    ai_provider: str | None = None
    ai_configured: bool | None = None
    app_mode: str | None = None
    storage_provider: str | None = None
    job_provider: str | None = None


class RuntimeModeResponse(ApiModel):
    mode: Literal["live", "deterministic_replay"]
    app_mode: Literal["demo", "development", "test", "staging", "production"]
    external_ai_enabled: bool
    label: str
    demo_canvas_id: uuid.UUID | None = None
    demo_trace_id: uuid.UUID | None = None


@router.get("/live", response_model=HealthResponse)
async def liveness(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="opencanvas-api",
        version=__version__,
        environment=settings.environment,
        app_mode=settings.runtime_mode.value,
    )


@router.get("/ready", response_model=HealthResponse)
async def readiness(settings: SettingsDep, session: SessionDep) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "database_unavailable",
            "The database is not ready.",
        ) from exc
    try:
        await build_document_storage(settings).healthcheck()
    except DocumentServiceError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "storage_unavailable",
            "The private document store is not ready.",
        ) from exc
    if settings.job_provider == "database":
        heartbeat = await session.scalar(
            select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
        )
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.worker_stale_after_seconds)
        if heartbeat is None or _as_utc(heartbeat.last_seen_at) < cutoff:
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "worker_unavailable",
                "The document worker is not ready.",
            )
    return HealthResponse(
        status="ready",
        service="opencanvas-api",
        version=__version__,
        environment=settings.environment,
        ai_provider=settings.effective_ai_provider,
        ai_configured=settings.openai_configured,
        app_mode=settings.runtime_mode.value,
        storage_provider=settings.storage_provider,
        job_provider=settings.job_provider,
    )


@router.get("/runtime", response_model=RuntimeModeResponse)
async def runtime_mode(settings: SettingsDep) -> RuntimeModeResponse:
    if settings.demo_mode:
        return RuntimeModeResponse(
            mode="deterministic_replay",
            app_mode="demo",
            external_ai_enabled=False,
            label="Build Week demo · deterministic replay · no external AI calls",
            demo_canvas_id=DEMO_CANVAS_ID,
            demo_trace_id=DEMO_TRACE_ID,
        )
    return RuntimeModeResponse(
        mode="live",
        app_mode=settings.runtime_mode.value,
        external_ai_enabled=settings.openai_configured,
        label=(
            f"{settings.runtime_mode.value.title()} · live providers"
            if settings.openai_configured
            else f"{settings.runtime_mode.value.title()} · deterministic local providers"
        ),
    )


@router.get("/worker", response_model=HealthResponse)
async def worker_health(settings: SettingsDep, session: SessionDep) -> HealthResponse:
    if settings.job_provider != "database":
        return HealthResponse(
            status="ready",
            service="opencanvas-worker-inline",
            version=__version__,
            environment=settings.environment,
            app_mode=settings.runtime_mode.value,
            job_provider=settings.job_provider,
        )
    heartbeat = await session.scalar(
        select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
    )
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.worker_stale_after_seconds)
    if heartbeat is None or _as_utc(heartbeat.last_seen_at) < cutoff:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "worker_unavailable",
            "The document worker is not ready.",
        )
    return HealthResponse(
        status="ready",
        service="opencanvas-worker",
        version=__version__,
        environment=settings.environment,
        app_mode=settings.runtime_mode.value,
        job_provider=settings.job_provider,
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
