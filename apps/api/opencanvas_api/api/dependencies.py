from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.errors import ApiError
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import SYSTEM_USER_ID, Canvas, Document
from opencanvas_api.db.session import Database
from opencanvas_api.services.ai import AIProvider, build_ai_provider
from opencanvas_api.services.auth import (
    AuthenticationError,
    Principal,
    csrf_matches,
    resolve_session,
)
from opencanvas_api.services.authorization import AuthorizationError, require_owned_workspace
from opencanvas_api.services.canonical.service import CanonicalService
from opencanvas_api.services.documents import (
    VersionedObjectStorage,
    build_versioned_object_storage,
)
from opencanvas_api.services.domain_events import DomainEventService
from opencanvas_api.services.knowledge_graph import KnowledgeGraphService
from opencanvas_api.services.rate_limits import (
    RateLimitDimension,
    SharedRateLimitService,
    SharedRateLimitUnavailable,
)
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


def get_versioned_object_storage(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionedObjectStorage:
    storage = cast(
        VersionedObjectStorage | None,
        getattr(request.app.state, "versioned_object_storage", None),
    )
    if storage is None:
        storage = build_versioned_object_storage(settings)
        request.app.state.versioned_object_storage = storage
    return storage


def get_trace_service(session: Annotated[AsyncSession, Depends(get_session)]) -> TraceService:
    return TraceService(session)


def get_canonical_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CanonicalService:
    return CanonicalService(session)


def get_knowledge_graph_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeGraphService:
    return KnowledgeGraphService(session)


def get_domain_event_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DomainEventService:
    return DomainEventService(session)


async def get_current_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if settings.demo_mode:
        from opencanvas_api.services.demo import DEMO_USER_ID

        return Principal(
            user_id=DEMO_USER_ID,
            email="demo@mobius.invalid",
            display_name="Competition demo",
            session_id=None,
            csrf_token_hash=None,
            synthetic=True,
        )
    if settings.auth_test_bypass and settings.runtime_mode.value == "test":
        return Principal(
            user_id=SYSTEM_USER_ID,
            email="test-system@mobius.invalid",
            display_name="Test system user",
            session_id=None,
            csrf_token_hash=None,
            synthetic=True,
        )
    if not settings.auth_enabled and settings.runtime_mode.value == "development":
        return Principal(
            user_id=SYSTEM_USER_ID,
            email="development@mobius.invalid",
            display_name="Local development",
            session_id=None,
            csrf_token_hash=None,
            synthetic=True,
        )
    raw_token = request.cookies.get(settings.session_cookie_name)
    authorization = request.headers.get("Authorization", "")
    if raw_token is None and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()
    if not raw_token:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_required",
            "Sign in to continue.",
        )
    try:
        return await resolve_session(session, raw_token=raw_token, settings=settings)
    except AuthenticationError as exc:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "session_expired",
            "Your session is invalid or has expired. Sign in again.",
        ) from exc


async def require_csrf_principal(
    request: Request,
    principal: Annotated[Principal, Depends(get_current_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if principal.synthetic or request.method in {"GET", "HEAD", "OPTIONS"}:
        return principal
    token = request.headers.get(settings.csrf_header_name)
    if not csrf_matches(principal, token, settings):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "csrf_validation_failed",
            "The request security token is invalid. Refresh and try again.",
        )
    return principal


async def require_path_workspace_principal(
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    raw_workspace_id = request.path_params.get("workspace_id")
    if raw_workspace_id is None:
        return principal
    try:
        workspace_id = uuid.UUID(str(raw_workspace_id))
        await require_owned_workspace(session, principal, workspace_id)
    except (ValueError, AuthorizationError) as exc:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            "Workspace not found.",
        ) from exc
    return principal


async def enforce_ai_rate_limit(
    request: Request,
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    dimensions = [
        RateLimitDimension(
            "user",
            str(principal.user_id),
            settings.ai_requests_per_user_per_minute,
        ),
        RateLimitDimension("provider", settings.ai_provider, 1_000),
    ]
    workspace_id = await _request_workspace_id(request, session)
    if workspace_id is not None:
        dimensions.append(
            RateLimitDimension(
                "workspace",
                str(workspace_id),
                settings.requests_per_workspace_per_minute,
            )
        )
    await _enforce_shared(request, operation="ai", dimensions=dimensions)


async def enforce_document_rate_limit(
    request: Request,
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    dimensions = [
        RateLimitDimension(
            "user",
            str(principal.user_id),
            settings.requests_per_user_per_minute,
        )
    ]
    workspace_id = await _request_workspace_id(request, session)
    if workspace_id is not None:
        dimensions.append(
            RateLimitDimension(
                "workspace",
                str(workspace_id),
                settings.requests_per_workspace_per_minute,
            )
        )
    resource_id = _request_resource_id(request)
    if resource_id is not None:
        dimensions.append(
            RateLimitDimension(
                "resource",
                resource_id,
                settings.requests_per_user_per_minute,
            )
        )
    await _enforce_shared(request, operation="documents", dimensions=dimensions)


async def enforce_scanner_result_rate_limit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    source = request.client.host if request.client is not None else "unknown"
    await _enforce_shared(
        request,
        operation="scanner-result",
        dimensions=[
            RateLimitDimension(
                "network",
                source,
                settings.scanner_result_requests_per_minute,
            ),
            RateLimitDimension(
                "provider",
                settings.malware_scanner_identity,
                settings.scanner_result_requests_per_minute,
            ),
        ],
    )


async def enforce_auth_rate_limit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    source = request.client.host if request.client is not None else "unknown"
    await _enforce_shared(
        request,
        operation="auth",
        dimensions=[
            RateLimitDimension(
                "network",
                source,
                settings.auth_requests_per_ip_per_minute,
            )
        ],
    )


async def _enforce_shared(
    request: Request,
    *,
    operation: str,
    dimensions: list[RateLimitDimension],
) -> None:
    limiter = getattr(request.app.state, "shared_rate_limiter", None)
    if not isinstance(limiter, SharedRateLimitService):
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "rate_limit_unavailable",
            "Request protection is temporarily unavailable.",
            headers={"Retry-After": "1"},
        )
    try:
        decision = await limiter.consume(operation=operation, dimensions=dimensions)
    except SharedRateLimitUnavailable as exc:
        limiter.metrics.responses_503 += 1
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "rate_limit_unavailable",
            "Request protection is temporarily unavailable.",
            headers={"Retry-After": "1"},
        ) from exc
    if not decision.allowed:
        limiter.metrics.responses_429 += 1
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limit_exceeded",
            "Too many expensive requests. Wait briefly and try again.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _request_resource_id(request: Request) -> str | None:
    for name in (
        "document_id",
        "canvas_id",
        "workflow_id",
        "execution_id",
        "agent_id",
    ):
        if value := request.path_params.get(name):
            return f"{name}:{value}"
    return None


async def _request_workspace_id(request: Request, session: AsyncSession) -> uuid.UUID | None:
    raw_canvas_id = request.path_params.get("canvas_id")
    if raw_canvas_id is not None:
        try:
            return cast(
                uuid.UUID | None,
                await session.scalar(
                    select(Canvas.workspace_id).where(Canvas.id == uuid.UUID(str(raw_canvas_id)))
                ),
            )
        except ValueError:
            return None
    raw_document_id = request.path_params.get("document_id")
    if raw_document_id is not None:
        try:
            return cast(
                uuid.UUID | None,
                await session.scalar(
                    select(Canvas.workspace_id)
                    .join(Document, Document.canvas_id == Canvas.id)
                    .where(Document.id == uuid.UUID(str(raw_document_id)))
                ),
            )
        except ValueError:
            return None
    return None


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]
MutatingPrincipalDep = Annotated[Principal, Depends(require_csrf_principal)]
