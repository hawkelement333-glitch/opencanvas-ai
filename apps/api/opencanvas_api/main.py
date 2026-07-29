import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from starlette.responses import Response

from opencanvas_api import __version__
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.router import api_router
from opencanvas_api.core.config import AppMode, DatabaseRole, get_settings
from opencanvas_api.db.runtime import DatabaseRuntimeError, validate_database_runtime
from opencanvas_api.db.session import Database
from opencanvas_api.services.documents import reconcile_interrupted_processing
from opencanvas_api.services.observability import (
    OperationalTelemetry,
    Severity,
    build_observability,
    classify_http_outcome,
    safe_route_template,
)
from opencanvas_api.services.rate_limits import build_shared_rate_limit_service

logger = structlog.get_logger("opencanvas_api")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database.from_settings(settings, expected_role=DatabaseRole.API)
    application.state.database = database
    telemetry: OperationalTelemetry = application.state.observability
    rate_limiter = getattr(application.state, "shared_rate_limiter", None)
    if rate_limiter is None:
        rate_limiter = build_shared_rate_limit_service(settings)
        application.state.shared_rate_limiter = rate_limiter
    try:
        try:
            await validate_database_runtime(
                database.engine, settings, expected_role=DatabaseRole.API
            )
            async with database.engine.connect() as connection:
                has_document_table = await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).has_table("documents")
                )
            if has_document_table:
                async with database.sessions() as session:
                    await reconcile_interrupted_processing(session)
        except DatabaseRuntimeError as exc:
            logger.warning("database_not_ready_at_startup", error_category=exc.code)
        if (
            settings.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}
            and not await rate_limiter.health()
        ):
            raise RuntimeError("The managed shared rate limiter is not ready.")
        yield
    finally:
        await telemetry.close()
        await rate_limiter.close()
        await database.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="SolarPlexus Mobius API",
        version=__version__,
        docs_url=(
            "/docs" if settings.runtime_mode.value in {"demo", "development", "test"} else None
        ),
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.observability = build_observability(settings)
    application.state.shared_rate_limiter = build_shared_rate_limit_service(settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "If-Match",
            "X-Scanner-Result-Signature",
            "X-Upload-Capability",
            settings.correlation_header_name,
            settings.csrf_header_name,
            "traceparent",
            "baggage",
        ],
        expose_headers=[settings.correlation_header_name, "traceparent"],
    )

    @application.middleware("http")
    async def request_observability(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        telemetry: OperationalTelemetry = request.app.state.observability
        request_id = uuid.uuid4().hex
        request_correlation = telemetry.correlate(
            "request",
            request_id,
            scope=(settings.runtime_mode.value, settings.telemetry_deployment),
        )
        request.state.correlation_id = request_id
        request.state.operational_correlation = request_correlation
        span = telemetry.start_span(
            "http.server.request",
            component="api",
            attributes={"operation": "http_request", "component": "api"},
        )
        content_length = request.headers.get("Content-Length")
        started = time.perf_counter()
        try:
            if content_length is not None:
                try:
                    parsed_content_length = int(content_length)
                except ValueError:
                    parsed_content_length = None
                    response: Response = JSONResponse(
                        status_code=400,
                        content={
                            "code": "invalid_content_length",
                            "detail": "The request content length is invalid.",
                        },
                        headers={settings.correlation_header_name: request_id},
                    )
                if (
                    parsed_content_length is not None
                    and parsed_content_length > settings.request_max_body_bytes
                ):
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "code": "request_too_large",
                            "detail": "The request exceeds the configured size limit.",
                        },
                        headers={settings.correlation_header_name: request_id},
                    )
                elif parsed_content_length is not None:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception:
            span.end(outcome="server_error", failure_class="unhandled_exception")
            raise
        latency_ms = int((time.perf_counter() - started) * 1_000)
        response.headers[settings.correlation_header_name] = request_id
        response.headers["traceparent"] = span.context.traceparent
        outcome = classify_http_outcome(response.status_code)
        method = (
            request.method
            if request.method
            in {
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "OPTIONS",
                "HEAD",
            }
            else "other"
        )
        route = safe_route_template(request.scope.get("route"))
        telemetry.emit_log(
            event_name="api.request.completed",
            severity=Severity.INFO if response.status_code < 500 else Severity.ERROR,
            component="api",
            fields={
                "operation": "http_request",
                "route": route,
                "method": method,
                "status_code": response.status_code,
                "status_class": f"{response.status_code // 100}xx",
                "outcome": outcome,
                "duration_ms": latency_ms,
                "correlation_kind": "request",
                "correlation": request_correlation,
            },
            trace=span.context,
        )
        telemetry.record_metric(
            "mobius.api.requests",
            1,
            labels={"method": method, "outcome": outcome},
        )
        telemetry.record_metric(
            "mobius.api.duration",
            latency_ms,
            labels={"method": method, "outcome": outcome},
        )
        if response.status_code >= 500:
            telemetry.record_metric(
                "mobius.api.errors",
                1,
                labels={"component": "api", "outcome": outcome},
            )
        span.end(outcome=outcome)
        telemetry.schedule_flush()
        return response

    @application.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), geolocation=(), microphone=()"
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        if settings.secure_cookies:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @application.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", uuid.uuid4().hex)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "detail": exc.message,
            },
            headers={
                settings.correlation_header_name: correlation_id,
                **(exc.headers or {}),
            },
        )

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", uuid.uuid4().hex)
        telemetry: OperationalTelemetry = request.app.state.observability
        telemetry.emit_log(
            event_name="api.request.failed",
            severity=Severity.ERROR,
            component="api",
            fields={
                "operation": "http_request",
                "method": (
                    request.method
                    if request.method
                    in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
                    else "other"
                ),
                "route": safe_route_template(request.scope.get("route")),
                "status_code": 500,
                "status_class": "5xx",
                "outcome": "server_error",
                "failure_class": "unhandled_exception",
                "correlation_kind": "request",
                "correlation": telemetry.correlate(
                    "request",
                    correlation_id,
                    scope=(settings.runtime_mode.value, settings.telemetry_deployment),
                ),
            },
        )
        del exc
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "detail": "The request could not be completed.",
            },
            headers={settings.correlation_header_name: correlation_id},
        )

    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
