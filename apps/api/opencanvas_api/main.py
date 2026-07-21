import re
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
from opencanvas_api.core.config import get_settings
from opencanvas_api.db.session import Database
from opencanvas_api.services.documents import reconcile_interrupted_processing

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
logger = structlog.get_logger("opencanvas_api")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(
        settings.database_url,
        pool_size=settings.database_pool_size,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
    )
    application.state.database = database
    try:
        async with database.engine.connect() as connection:
            has_document_table = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).has_table("documents")
            )
        if has_document_table:
            async with database.sessions() as session:
                await reconcile_interrupted_processing(session)
        yield
    finally:
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
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "If-Match",
            settings.correlation_header_name,
            settings.csrf_header_name,
        ],
    )

    @application.middleware("http")
    async def request_observability(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied_id = request.headers.get(settings.correlation_header_name)
        correlation_id = (
            supplied_id if supplied_id and _REQUEST_ID.fullmatch(supplied_id) else uuid.uuid4().hex
        )
        request.state.correlation_id = correlation_id
        content_length = request.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > settings.request_max_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "code": "request_too_large",
                            "detail": "The request exceeds the configured size limit.",
                            "correlationId": correlation_id,
                        },
                        headers={settings.correlation_header_name: correlation_id},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "code": "invalid_content_length",
                        "detail": "The request content length is invalid.",
                        "correlationId": correlation_id,
                    },
                    headers={settings.correlation_header_name: correlation_id},
                )
        started = time.perf_counter()
        response = await call_next(request)
        latency_ms = int((time.perf_counter() - started) * 1_000)
        response.headers[settings.correlation_header_name] = correlation_id
        logger.info(
            "request_completed",
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
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
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "detail": exc.message,
            },
            headers=exc.headers,
        )

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", uuid.uuid4().hex)
        logger.error(
            "request_failed",
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
            error_category=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "detail": "The request could not be completed.",
            },
        )

    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
