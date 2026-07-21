from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import Canvas, Document, TraceEvent, Workspace
from opencanvas_api.services.auth import Principal


class AuthorizationError(RuntimeError):
    pass


async def require_owned_workspace(
    session: AsyncSession, principal: Principal, workspace_id: uuid.UUID
) -> Workspace:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == principal.user_id,
            Workspace.deleted_at.is_(None),
            Workspace.lifecycle_state != "deleted",
        )
    )
    if workspace is None:
        raise AuthorizationError("The requested resource was not found.")
    return workspace


async def require_owned_canvas(
    session: AsyncSession, principal: Principal, canvas_id: uuid.UUID
) -> Canvas:
    canvas = await session.scalar(
        select(Canvas)
        .join(Workspace, Workspace.id == Canvas.workspace_id)
        .where(
            Canvas.id == canvas_id,
            Workspace.owner_id == principal.user_id,
            Workspace.deleted_at.is_(None),
            Workspace.lifecycle_state != "deleted",
        )
    )
    if canvas is None:
        raise AuthorizationError("The requested resource was not found.")
    return canvas


async def require_owned_document(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID
) -> Document:
    document = await session.scalar(
        select(Document)
        .join(Canvas, Canvas.id == Document.canvas_id)
        .join(Workspace, Workspace.id == Canvas.workspace_id)
        .where(
            Document.id == document_id,
            Workspace.owner_id == principal.user_id,
            Workspace.deleted_at.is_(None),
            Workspace.lifecycle_state != "deleted",
            Document.deleted_at.is_(None),
            Document.status != "deleted",
        )
    )
    if document is None:
        raise AuthorizationError("The requested resource was not found.")
    return document


async def require_trace_workspace(
    session: AsyncSession, principal: Principal, trace_id: uuid.UUID
) -> uuid.UUID:
    workspace_id = await session.scalar(
        select(TraceEvent.workspace_id)
        .join(Workspace, Workspace.id == TraceEvent.workspace_id)
        .where(TraceEvent.trace_id == trace_id, Workspace.owner_id == principal.user_id)
        .limit(1)
    )
    if workspace_id is None:
        raise AuthorizationError("The requested resource was not found.")
    return workspace_id


__all__ = [
    "AuthorizationError",
    "require_owned_canvas",
    "require_owned_document",
    "require_owned_workspace",
    "require_trace_workspace",
]
