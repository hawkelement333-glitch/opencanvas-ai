"""Private authenticated service for the existing deterministic activity-v1 projection."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from opencanvas_api.core.config import AppMode, DatabaseRole, Settings, get_settings
from opencanvas_api.db.runtime import validate_database_runtime
from opencanvas_api.db.session import Database
from opencanvas_api.services.domain_events import (
    DomainEventConflictError,
    DomainEventValidationError,
    OutboxOwnershipError,
)
from opencanvas_api.services.outbox_dispatcher import (
    DeliveryEnvelope,
    DurableActivityConsumer,
    acknowledgment_bytes,
    acknowledgment_signature,
)


def create_receiver(settings: Settings, database: Database) -> FastAPI:
    if settings.outbox_delivery_secret is None or settings.runtime_mode is AppMode.DEMO:
        raise ValueError("Activity receiver needs dedicated configured authority.")
    secret = settings.outbox_delivery_secret.get_secret_value()
    consumer = DurableActivityConsumer(database.sessions)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/ready")
    async def ready() -> Response:
        try:
            await validate_database_runtime(
                database.engine, settings, expected_role=DatabaseRole.WORKER
            )
        except Exception:
            return Response(status_code=503)
        return Response(status_code=204)

    @app.post("/v1/activity-deliveries")
    async def deliver(request: Request) -> Response:
        if not hmac.compare_digest(
            request.headers.get("authorization", "").encode("utf-8"),
            ("Bearer " + secret).encode("ascii"),
        ):
            return Response(status_code=401)
        if request.headers.get("content-type") != "application/json":
            return Response(status_code=415)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                return Response(status_code=413)
        try:
            claim = DeliveryEnvelope.model_validate_json(bytes(raw)).claim()
            receipt = await consumer.deliver(claim)
            encoded = acknowledgment_bytes(claim, receipt)
        except ValidationError:
            return Response(status_code=422)
        except OutboxOwnershipError:
            return Response(status_code=409)
        except (DomainEventConflictError, DomainEventValidationError):
            return Response(status_code=422)
        except SQLAlchemyError:
            return Response(status_code=503)
        return Response(
            content=encoded,
            media_type="application/json",
            headers={"X-Activity-Acknowledgment": acknowledgment_signature(encoded, secret)},
        )

    return app


def application() -> FastAPI:
    settings = get_settings()
    database = Database.from_settings(settings, expected_role=DatabaseRole.WORKER)
    app = create_receiver(settings, database)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            await validate_database_runtime(
                database.engine, settings, expected_role=DatabaseRole.WORKER
            )
            yield
        finally:
            await database.dispose()

    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("scripts.activity_receiver:application", factory=True, host="0.0.0.0", port=8011)
