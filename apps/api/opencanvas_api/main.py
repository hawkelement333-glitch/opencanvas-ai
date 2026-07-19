from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(settings.database_url)
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
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "If-Match", "X-Request-ID"],
    )

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
        return response

    @application.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.message},
            headers=exc.headers,
        )

    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
