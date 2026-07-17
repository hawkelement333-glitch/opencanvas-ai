import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api import __version__
from opencanvas_api.api.dependencies import get_session
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.services.demo import DEMO_CANVAS_ID, DEMO_TRACE_ID

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


class RuntimeModeResponse(ApiModel):
    mode: Literal["live", "deterministic_replay"]
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
    return HealthResponse(
        status="ready",
        service="opencanvas-api",
        version=__version__,
        environment=settings.environment,
        ai_provider=settings.effective_ai_provider,
        ai_configured=settings.openai_configured,
    )


@router.get("/runtime", response_model=RuntimeModeResponse)
async def runtime_mode(settings: SettingsDep) -> RuntimeModeResponse:
    if settings.demo_mode:
        return RuntimeModeResponse(
            mode="deterministic_replay",
            external_ai_enabled=False,
            label="Build Week demo · deterministic replay · no external AI calls",
            demo_canvas_id=DEMO_CANVAS_ID,
            demo_trace_id=DEMO_TRACE_ID,
        )
    return RuntimeModeResponse(
        mode="live",
        external_ai_enabled=settings.openai_configured,
        label=("Live model mode" if settings.openai_configured else "Local mock AI mode"),
    )
