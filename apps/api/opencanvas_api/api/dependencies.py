from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.errors import ApiError
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.session import Database
from opencanvas_api.services.ai import AIProvider, build_ai_provider
from opencanvas_api.services.canonical.service import CanonicalService
from opencanvas_api.services.trace import TraceService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.sessions() as session:
        yield session


def get_ai_provider(settings: Annotated[Settings, Depends(get_settings)]) -> AIProvider:
    return build_ai_provider(settings)


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_trace_service(session: Annotated[AsyncSession, Depends(get_session)]) -> TraceService:
    return TraceService(session)


def get_canonical_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CanonicalService:
    return CanonicalService(session)


@dataclass(slots=True)
class InMemoryRateLimiter:
    """Small per-process limiter for expensive unauthenticated MVP operations."""

    _requests: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def enforce(self, key: str, *, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= limit:
                retry_after = max(1, int(window_seconds - (now - timestamps[0])))
                raise ApiError(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "rate_limit_exceeded",
                    "Too many expensive requests. Wait briefly and try again.",
                    headers={"Retry-After": str(retry_after)},
                )
            timestamps.append(now)


def _client_key(request: Request, operation: str) -> str:
    client_host = request.client.host if request.client is not None else "unknown"
    return f"{operation}:{client_host}"


async def enforce_ai_rate_limit(request: Request) -> None:
    limiter = getattr(request.app.state, "expensive_operation_limiter", None)
    if not isinstance(limiter, InMemoryRateLimiter):
        limiter = InMemoryRateLimiter()
        request.app.state.expensive_operation_limiter = limiter
    await limiter.enforce(_client_key(request, "ai"), limit=30, window_seconds=60.0)


async def enforce_document_rate_limit(request: Request) -> None:
    limiter = getattr(request.app.state, "expensive_operation_limiter", None)
    if not isinstance(limiter, InMemoryRateLimiter):
        limiter = InMemoryRateLimiter()
        request.app.state.expensive_operation_limiter = limiter
    await limiter.enforce(_client_key(request, "documents"), limit=60, window_seconds=60.0)
