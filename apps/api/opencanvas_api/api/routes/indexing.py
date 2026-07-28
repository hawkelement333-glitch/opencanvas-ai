from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    enforce_document_rate_limit,
    get_database,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import IndexRequestCreate, IndexRequestOut, IndexRevisionOut
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    Document,
    IndexPublication,
    RetrievalHead,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.documents import build_document_storage, build_embedding_provider
from opencanvas_api.services.indexer import (
    IndexerError,
    IngestionService,
    IngestionView,
    process_ingestion_request,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/canvases/{canvas_id}")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]


def _error(error: IndexerError) -> ApiError:
    return ApiError(error.status_code, error.code, error.safe_message)


def _service(session: AsyncSession, settings: Settings) -> IngestionService:
    return IngestionService(
        session,
        settings=settings,
        storage=build_document_storage(settings),
        provider=build_embedding_provider(settings),
    )


def _request_out(view: IngestionView) -> IndexRequestOut:
    terminal = {"published", "failed", "canceled", "superseded"}
    return IndexRequestOut(
        request_id=view.request.request_id,
        workspace_id=view.request.workspace_id,
        canvas_id=view.request.canvas_id,
        document_id=view.request.document_id,
        document_version=view.request.document_version,
        operation=view.request.operation,
        state=view.transition.current_state,
        reason_code=view.transition.reason_code,
        trace_id=view.request.trace_id,
        revision_id=view.revision.revision_id if view.revision is not None else None,
        publication_id=(view.publication.publication_id if view.publication is not None else None),
        duplicate=view.duplicate,
        cancellable=view.transition.current_state not in terminal,
        created_at=view.request.created_at,
        updated_at=view.transition.recorded_at,
    )


def _schedule(
    background_tasks: BackgroundTasks,
    *,
    database: Database,
    settings: Settings,
    view: IngestionView,
) -> None:
    if view.duplicate or view.transition.current_state != "queued":
        return
    background_tasks.add_task(
        process_ingestion_request,
        database.sessions,
        request_id=view.request.request_id,
        settings=settings,
        storage=build_document_storage(settings),
        provider=build_embedding_provider(settings),
    )


@router.post(
    "/documents/{document_id}/versions/{document_version}/index-requests",
    response_model=IndexRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def request_index(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    document_id: uuid.UUID,
    document_version: int,
    payload: IndexRequestCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
) -> IndexRequestOut:
    try:
        view = await _service(session, settings).request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=document_version,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except IndexerError as exc:
        await session.rollback()
        raise _error(exc) from exc
    _schedule(background_tasks, database=database, settings=settings, view=view)
    return _request_out(view)


@router.get("/index-requests/{request_id}", response_model=IndexRequestOut)
async def get_index_request(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    request_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> IndexRequestOut:
    try:
        return _request_out(
            await _service(session, settings).get(
                principal=principal,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                request_id=request_id,
            )
        )
    except IndexerError as exc:
        raise _error(exc) from exc


@router.post(
    "/index-requests/{request_id}/cancel",
    response_model=IndexRequestOut,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def cancel_index_request(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    request_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> IndexRequestOut:
    try:
        view = await _service(session, settings).cancel(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            request_id=request_id,
        )
        await session.commit()
    except IndexerError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _request_out(view)


@router.post(
    "/documents/{document_id}/reindex",
    response_model=IndexRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_document_rate_limit)],
)
async def reindex_document(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: IndexRequestCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    database: DatabaseDep,
    background_tasks: BackgroundTasks,
) -> IndexRequestOut:
    document_version = await session.scalar(
        select(Document.current_version).where(
            Document.id == document_id,
            Document.canvas_id == canvas_id,
            Document.deleted_at.is_(None),
        )
    )
    if document_version is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "index_not_found", "The index was not found.")
    try:
        view = await _service(session, settings).request(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=document_version,
            idempotency_key=payload.idempotency_key,
            operation="reindex",
        )
        await session.commit()
    except IndexerError as exc:
        await session.rollback()
        raise _error(exc) from exc
    _schedule(background_tasks, database=database, settings=settings, view=view)
    return _request_out(view)


@router.get("/documents/{document_id}/index-revisions", response_model=list[IndexRevisionOut])
async def list_index_revisions(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[IndexRevisionOut]:
    try:
        revisions = await _service(session, settings).list_revisions(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            limit=limit,
        )
    except IndexerError as exc:
        raise _error(exc) from exc
    head = await session.get(RetrievalHead, document_id)
    publications = {
        publication.revision_id: publication.generation
        for publication in (
            await session.scalars(
                select(IndexPublication).where(
                    IndexPublication.workspace_id == workspace_id,
                    IndexPublication.document_id == document_id,
                    IndexPublication.revision_id.in_(
                        [revision.revision_id for revision in revisions]
                    ),
                )
            )
        ).all()
    }
    return [
        IndexRevisionOut(
            revision_id=revision.revision_id,
            document_id=revision.document_id,
            document_version=revision.document_version,
            status="completed",
            active=head is not None and head.revision_id == revision.revision_id,
            publication_generation=publications.get(revision.revision_id),
            created_at=revision.created_at,
        )
        for revision in revisions
    ]
