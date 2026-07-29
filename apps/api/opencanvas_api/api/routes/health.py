import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import PrincipalDep, get_database, get_session
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.core.config import DatabaseRole, Settings, get_settings
from opencanvas_api.db.models import WorkerHeartbeat
from opencanvas_api.db.runtime import DatabaseRuntimeError, validate_database_runtime
from opencanvas_api.db.session import Database
from opencanvas_api.services.demo import DEMO_CANVAS_ID, DEMO_TRACE_ID
from opencanvas_api.services.documents import DocumentServiceError, build_document_storage
from opencanvas_api.services.observability import (
    OperationalHealth,
    OperationalTelemetry,
    Severity,
)
from opencanvas_api.services.rate_limits import SharedRateLimitService

router = APIRouter(prefix="/health")
SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
DatabaseDep = Annotated[Database, Depends(get_database)]
DependencyName = Literal["database", "storage", "limiter", "worker", "telemetry"]
DependencyState = Literal["healthy", "degraded", "unavailable", "indeterminate", "disabled"]


class PublicHealthResponse(BaseModel):
    status: Literal["ok", "ready"]
    service: str


class OperatorHealthResponse(ApiModel):
    status: Literal["healthy", "degraded", "unavailable", "indeterminate"]
    service: str
    release: str
    deployment: str
    schema_revision: str
    dependencies: dict[DependencyName, DependencyState]
    telemetry_buffered: int
    telemetry_dropped: int
    telemetry_rejected: int


class RuntimeModeResponse(ApiModel):
    mode: Literal["live", "deterministic_replay"]
    app_mode: Literal["demo", "development", "test", "staging", "production"]
    external_ai_enabled: bool
    label: str
    demo_canvas_id: uuid.UUID | None = None
    demo_trace_id: uuid.UUID | None = None


@router.get("/live", response_model=PublicHealthResponse)
async def liveness(settings: SettingsDep) -> PublicHealthResponse:
    del settings
    return PublicHealthResponse(
        status="ok",
        service="opencanvas-api",
    )


@router.get("/ready", response_model=PublicHealthResponse)
async def readiness(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    database: DatabaseDep,
) -> PublicHealthResponse:
    dependencies = await _dependency_states(
        request=request,
        settings=settings,
        session=session,
        database=database,
    )
    if any(value in {"unavailable", "indeterminate"} for value in dependencies.values()):
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "service_not_ready",
            "The service is not ready.",
        )
    return PublicHealthResponse(
        status="ready",
        service="opencanvas-api",
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


@router.get("/worker", response_model=PublicHealthResponse)
async def worker_health(settings: SettingsDep, session: SessionDep) -> PublicHealthResponse:
    if settings.job_provider != "database":
        return PublicHealthResponse(
            status="ready",
            service="opencanvas-worker-inline",
        )
    heartbeat = await session.scalar(
        select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
    )
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.worker_stale_after_seconds)
    if (
        heartbeat is None
        or heartbeat.status not in {"ready", "processing"}
        or _as_utc(heartbeat.last_seen_at) < cutoff
    ):
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "worker_unavailable",
            "The document worker is not ready.",
        )
    return PublicHealthResponse(
        status="ready",
        service="opencanvas-worker",
    )


@router.get("/operator", response_model=OperatorHealthResponse)
async def operator_health(
    request: Request,
    principal: PrincipalDep,
    settings: SettingsDep,
    session: SessionDep,
    database: DatabaseDep,
) -> OperatorHealthResponse:
    if principal.user_id not in set(settings.observability_operator_user_ids):
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "health_not_found",
            "Health detail is unavailable.",
        )
    dependencies = await _dependency_states(
        request=request,
        settings=settings,
        session=session,
        database=database,
    )
    telemetry: OperationalTelemetry = request.app.state.observability
    telemetry.emit_log(
        event_name="operator.health.accessed",
        severity=Severity.INFO,
        component="telemetry",
        fields={
            "operation": "operator_health",
            "outcome": "success",
            "state": _overall_health(dependencies),
            "correlation_kind": "request",
            "correlation": request.state.operational_correlation,
        },
        security=True,
    )
    return OperatorHealthResponse(
        status=_overall_health(dependencies),
        service=settings.telemetry_service_name,
        release=settings.telemetry_release,
        deployment=settings.telemetry_deployment,
        schema_revision=settings.database_expected_revision,
        dependencies=dependencies,
        telemetry_buffered=telemetry.buffered,
        telemetry_dropped=telemetry.counters.dropped,
        telemetry_rejected=telemetry.counters.rejected,
    )


async def _dependency_states(
    *,
    request: Request,
    settings: Settings,
    session: AsyncSession,
    database: Database,
) -> dict[DependencyName, DependencyState]:
    states: dict[DependencyName, DependencyState] = {
        "database": "indeterminate",
        "storage": "indeterminate",
        "limiter": "indeterminate",
        "worker": "indeterminate",
        "telemetry": "indeterminate",
    }
    try:
        await validate_database_runtime(database.engine, settings, expected_role=DatabaseRole.API)
    except DatabaseRuntimeError:
        states["database"] = "unavailable"
    else:
        states["database"] = "healthy"
    try:
        await build_document_storage(settings).healthcheck()
    except DocumentServiceError:
        states["storage"] = "unavailable"
    else:
        states["storage"] = "healthy"
    limiter = getattr(request.app.state, "shared_rate_limiter", None)
    states["limiter"] = (
        "healthy"
        if isinstance(limiter, SharedRateLimitService) and await limiter.health()
        else "unavailable"
    )
    if settings.job_provider != "database":
        states["worker"] = "healthy"
    else:
        heartbeat = await session.scalar(
            select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
        )
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.worker_stale_after_seconds)
        states["worker"] = (
            "healthy"
            if (
                heartbeat is not None
                and heartbeat.status in {"ready", "processing"}
                and _as_utc(heartbeat.last_seen_at) >= cutoff
            )
            else "unavailable"
        )
    telemetry = getattr(request.app.state, "observability", None)
    if not isinstance(telemetry, OperationalTelemetry):
        states["telemetry"] = "indeterminate"
    else:
        telemetry_health = telemetry.health()
        states["telemetry"] = telemetry_health.value
        if telemetry_health is OperationalHealth.DISABLED and settings.runtime_mode.value in {
            "staging",
            "production",
        }:
            states["telemetry"] = "unavailable"
    return states


def _overall_health(
    dependencies: Mapping[DependencyName, DependencyState],
) -> Literal["healthy", "degraded", "unavailable", "indeterminate"]:
    values = set(dependencies.values())
    if "unavailable" in values:
        return "unavailable"
    if "indeterminate" in values:
        return "indeterminate"
    if "degraded" in values:
        return "degraded"
    return "healthy"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
