from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, NoReturn, cast

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    enforce_ai_rate_limit,
    get_ai_provider,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import (
    AIQuery,
    AIQueryOut,
    CanvasCreate,
    CanvasOut,
    CanvasPatch,
    CitationOut,
    EdgeCreate,
    EdgeKind,
    EdgeOut,
    NodeCreate,
    NodeDuplicate,
    NodeOut,
    NodePatch,
    Point,
    SnapshotOut,
    Viewport,
)
from opencanvas_api.api.serialization import document_metadata_out, enrich_nodes, node_out, utc
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    AIClaim,
    AIExecutionChunk,
    AIExecutionCitation,
    AIExecutionNode,
    AIExecutionSource,
    AIRequest,
    AIResponse,
    AIResponseSource,
    Canvas,
    CanvasDocumentNode,
    CanvasNode,
    Citation,
    Document,
    DocumentFile,
    Edge,
    UsageRecord,
    Workspace,
)
from opencanvas_api.services.ai import (
    GROUNDED_PROMPT_VERSION,
    NOTE_PROMPT_VERSION,
    AIProvider,
    AIProviderError,
    GroundedAIResult,
    GroundedSource,
    model_configuration,
    validate_grounded_result,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.authorization import (
    AuthorizationError,
    require_owned_canvas,
    require_owned_workspace,
)
from opencanvas_api.services.context import build_context
from opencanvas_api.services.documents import (
    DocumentServiceError,
    RetrievedChunk,
    build_document_storage,
    build_embedding_provider,
    search_documents,
)
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    FailTraceInput,
    StartTraceInput,
    TraceErrorInfo,
    TraceService,
)

router = APIRouter(prefix="/canvases")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RevisionQuery = Annotated[int, Query(ge=0)]


def _canvas_out(canvas: Canvas) -> CanvasOut:
    return CanvasOut(
        id=canvas.id,
        workspace_id=canvas.workspace_id,
        name=canvas.name,
        viewport=Viewport(x=canvas.viewport_x, y=canvas.viewport_y, zoom=canvas.viewport_zoom),
        revision=canvas.revision,
        created_at=utc(canvas.created_at),
        updated_at=utc(canvas.updated_at),
    )


def _edge_out(edge: Edge) -> EdgeOut:
    return EdgeOut(
        id=edge.id,
        canvas_id=edge.canvas_id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        kind=cast(EdgeKind, edge.kind),
        label=edge.label,
        revision=edge.revision,
        created_at=utc(edge.created_at),
        updated_at=utc(edge.updated_at),
    )


async def _require_canvas(
    session: AsyncSession, canvas_id: uuid.UUID, principal: Principal
) -> Canvas:
    try:
        return await require_owned_canvas(session, principal, canvas_id)
    except AuthorizationError as exc:
        raise ApiError(status.HTTP_404_NOT_FOUND, "canvas_not_found", "Canvas not found.") from exc


async def _raise_node_missing_or_stale(
    session: AsyncSession, canvas_id: uuid.UUID, node_id: uuid.UUID
) -> NoReturn:
    exists = await session.scalar(
        select(CanvasNode.id).where(CanvasNode.id == node_id, CanvasNode.canvas_id == canvas_id)
    )
    if exists is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "node_not_found", "Node not found.")
    raise ApiError(
        status.HTTP_409_CONFLICT,
        "revision_conflict",
        "The node changed since it was loaded. Refresh and try again.",
    )


async def _bump_canvas(session: AsyncSession, canvas_id: uuid.UUID) -> None:
    await session.execute(
        update(Canvas)
        .where(Canvas.id == canvas_id)
        .values(revision=Canvas.revision + 1, updated_at=func.now())
    )


@router.get("", response_model=list[CanvasOut])
async def list_canvases(
    principal: PrincipalDep,
    session: SessionDep,
    workspace_id: Annotated[uuid.UUID | None, Query(alias="workspaceId")] = None,
) -> list[CanvasOut]:
    if workspace_id is not None:
        try:
            await require_owned_workspace(session, principal, workspace_id)
        except AuthorizationError as exc:
            raise ApiError(
                status.HTTP_404_NOT_FOUND, "workspace_not_found", "Workspace not found."
            ) from exc
    filters = [Workspace.owner_id == principal.user_id, Workspace.deleted_at.is_(None)]
    if workspace_id is not None:
        filters.append(Canvas.workspace_id == workspace_id)
    canvases = (
        await session.scalars(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(*filters)
            .order_by(Canvas.updated_at.desc(), Canvas.id)
        )
    ).all()
    return [_canvas_out(canvas) for canvas in canvases]


@router.post("", response_model=CanvasOut, status_code=status.HTTP_201_CREATED)
async def create_canvas(
    payload: CanvasCreate, principal: MutatingPrincipalDep, session: SessionDep
) -> CanvasOut:
    workspace = None
    if payload.workspace_id is not None:
        try:
            workspace = await require_owned_workspace(session, principal, payload.workspace_id)
        except AuthorizationError as exc:
            raise ApiError(
                status.HTTP_404_NOT_FOUND, "workspace_not_found", "Workspace not found."
            ) from exc
    else:
        workspace = await session.scalar(
            select(Workspace)
            .where(
                Workspace.owner_id == principal.user_id,
                Workspace.deleted_at.is_(None),
                Workspace.lifecycle_state != "deleted",
            )
            .order_by(Workspace.created_at, Workspace.id)
        )
    if workspace is None:
        workspace = Workspace(
            owner_id=principal.user_id,
            name=f"{principal.display_name}'s workspace",
            lifecycle_state="active",
        )
        session.add(workspace)
        await session.flush()
    canvas = Canvas(name=payload.name, workspace_id=workspace.id)
    session.add(canvas)
    await session.commit()
    await session.refresh(canvas)
    return _canvas_out(canvas)


@router.get("/{canvas_id}", response_model=CanvasOut)
async def get_canvas(
    canvas_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> CanvasOut:
    return _canvas_out(await _require_canvas(session, canvas_id, principal))


@router.patch("/{canvas_id}", response_model=CanvasOut)
async def patch_canvas(
    canvas_id: uuid.UUID,
    payload: CanvasPatch,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> CanvasOut:
    await _require_canvas(session, canvas_id, principal)
    values: dict[str, object] = {
        "revision": Canvas.revision + 1,
        "updated_at": func.now(),
    }
    if payload.name is not None:
        values["name"] = payload.name
    if payload.viewport is not None:
        values.update(
            viewport_x=payload.viewport.x,
            viewport_y=payload.viewport.y,
            viewport_zoom=payload.viewport.zoom,
        )
    canvas = (
        await session.execute(
            update(Canvas)
            .where(Canvas.id == canvas_id, Canvas.revision == payload.revision)
            .values(**values)
            .returning(Canvas)
        )
    ).scalar_one_or_none()
    if canvas is None:
        if await session.get(Canvas, canvas_id) is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, "canvas_not_found", "Canvas not found.")
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "revision_conflict",
            "The canvas changed since it was loaded. Refresh and try again.",
        )
    await session.commit()
    await session.refresh(canvas)
    return _canvas_out(canvas)


@router.delete("/{canvas_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_canvas(
    canvas_id: uuid.UUID,
    revision: RevisionQuery,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    await _require_canvas(session, canvas_id, principal)
    storage_keys = list(
        (
            await session.scalars(
                select(DocumentFile.storage_key)
                .join(Document, Document.id == DocumentFile.document_id)
                .where(Document.canvas_id == canvas_id)
            )
        ).all()
    )
    deleted = await session.scalar(
        delete(Canvas)
        .where(Canvas.id == canvas_id, Canvas.revision == revision)
        .returning(Canvas.id)
    )
    if deleted is None:
        if await session.get(Canvas, canvas_id) is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, "canvas_not_found", "Canvas not found.")
        raise ApiError(status.HTTP_409_CONFLICT, "revision_conflict", "Canvas revision is stale.")
    storage = build_document_storage(settings)
    try:
        for storage_key in storage_keys:
            await storage.delete(storage_key)
    except DocumentServiceError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, exc.safe_message) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{canvas_id}/snapshot", response_model=SnapshotOut)
async def get_snapshot(
    canvas_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> SnapshotOut:
    if session.get_bind().dialect.name == "postgresql":
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    canvas = await _require_canvas(session, canvas_id, principal)
    nodes = (
        await session.scalars(
            select(CanvasNode)
            .where(CanvasNode.canvas_id == canvas_id)
            .order_by(CanvasNode.created_at, CanvasNode.id)
        )
    ).all()
    edges = (
        await session.scalars(
            select(Edge).where(Edge.canvas_id == canvas_id).order_by(Edge.created_at, Edge.id)
        )
    ).all()
    document_by_node, citations_by_node = await enrich_nodes(session, nodes)
    return SnapshotOut(
        canvas=_canvas_out(canvas),
        nodes=[
            node_out(
                node,
                document=document_by_node.get(node.id),
                citations=citations_by_node.get(node.id),
            )
            for node in nodes
        ],
        edges=[_edge_out(edge) for edge in edges],
    )


@router.post("/{canvas_id}/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
async def create_node(
    canvas_id: uuid.UUID,
    payload: NodeCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> NodeOut:
    await _require_canvas(session, canvas_id, principal)
    if payload.type == "document":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "document_upload_required",
            "Create document nodes through the document upload endpoint.",
        )
    node = CanvasNode(
        canvas_id=canvas_id,
        type=payload.type,
        title=payload.title,
        text=payload.text,
        position_x=payload.position.x,
        position_y=payload.position.y,
        width=payload.width,
        height=payload.height,
    )
    session.add(node)
    await _bump_canvas(session, canvas_id)
    await session.commit()
    await session.refresh(node)
    return node_out(node)


@router.patch("/{canvas_id}/nodes/{node_id}", response_model=NodeOut)
async def patch_node(
    canvas_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: NodePatch,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> NodeOut:
    await _require_canvas(session, canvas_id, principal)
    persisted_node = await session.scalar(
        select(CanvasNode).where(
            CanvasNode.id == node_id,
            CanvasNode.canvas_id == canvas_id,
        )
    )
    invalidates_grounding = (
        persisted_node is not None
        and persisted_node.type == "ai_response"
        and payload.text is not None
        and payload.text != persisted_node.text
    )
    values: dict[str, object] = {
        "revision": CanvasNode.revision + 1,
        "updated_at": func.now(),
    }
    if payload.title is not None:
        values["title"] = payload.title
    if payload.text is not None:
        values["text"] = payload.text
    if payload.position is not None:
        values["position_x"] = payload.position.x
        values["position_y"] = payload.position.y
    if payload.width is not None:
        values["width"] = payload.width
    if payload.height is not None:
        values["height"] = payload.height
    node = (
        await session.execute(
            update(CanvasNode)
            .where(
                CanvasNode.id == node_id,
                CanvasNode.canvas_id == canvas_id,
                CanvasNode.revision == payload.revision,
            )
            .values(**values)
            .returning(CanvasNode)
        )
    ).scalar_one_or_none()
    if node is None:
        await _raise_node_missing_or_stale(session, canvas_id, node_id)
    if invalidates_grounding:
        response_id = await session.scalar(
            select(AIResponse.id).where(AIResponse.node_id == node_id)
        )
        if response_id is not None:
            await session.execute(delete(Citation).where(Citation.ai_response_id == response_id))
            await session.execute(
                delete(AIResponseSource).where(AIResponseSource.ai_response_id == response_id)
            )
            await session.execute(
                update(AIResponse).where(AIResponse.id == response_id).values(grounded=False)
            )
        await session.execute(
            delete(Edge).where(
                Edge.canvas_id == canvas_id,
                Edge.source_node_id == node_id,
                Edge.kind == "cites",
            )
        )
    await _bump_canvas(session, canvas_id)
    await session.commit()
    await session.refresh(node)
    return node_out(node)


@router.post(
    "/{canvas_id}/nodes/{node_id}/duplicate",
    response_model=NodeOut,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_node(
    canvas_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: NodeDuplicate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> NodeOut:
    await _require_canvas(session, canvas_id, principal)
    source = await session.scalar(
        select(CanvasNode).where(CanvasNode.id == node_id, CanvasNode.canvas_id == canvas_id)
    )
    if source is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "node_not_found", "Node not found.")
    if source.revision != payload.revision:
        raise ApiError(status.HTTP_409_CONFLICT, "revision_conflict", "Node revision is stale.")
    position = payload.position or Point(x=source.position_x + 40, y=source.position_y + 40)
    title = f"Copy of {source.title}"[:160]
    duplicate = CanvasNode(
        canvas_id=canvas_id,
        type=source.type,
        title=title,
        text=source.text,
        position_x=position.x,
        position_y=position.y,
        width=source.width,
        height=source.height,
    )
    session.add(duplicate)
    await session.flush()
    document_metadata = None
    if source.type == "document":
        reference = await session.get(CanvasDocumentNode, source.id)
        if reference is None:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "document_reference_missing",
                "The document node is missing its stored-document reference.",
            )
        session.add(
            CanvasDocumentNode(
                node_id=duplicate.id,
                canvas_id=canvas_id,
                document_id=reference.document_id,
            )
        )
        document = await session.get(Document, reference.document_id)
        if document is None:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "document_not_found",
                "The stored document is no longer available.",
            )
        document_metadata = document_metadata_out(document)
    await _bump_canvas(session, canvas_id)
    await session.commit()
    await session.refresh(duplicate)
    return node_out(duplicate, document=document_metadata)


@router.delete("/{canvas_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    canvas_id: uuid.UUID,
    node_id: uuid.UUID,
    revision: RevisionQuery,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> Response:
    await _require_canvas(session, canvas_id, principal)
    node = await session.scalar(
        select(CanvasNode).where(CanvasNode.id == node_id, CanvasNode.canvas_id == canvas_id)
    )
    if node is not None and node.type == "document":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "document_delete_required",
            "Delete document nodes through the document endpoint so stored content is cleaned up.",
        )
    deleted = await session.scalar(
        delete(CanvasNode)
        .where(
            CanvasNode.id == node_id,
            CanvasNode.canvas_id == canvas_id,
            CanvasNode.revision == revision,
        )
        .returning(CanvasNode.id)
    )
    if deleted is None:
        await _raise_node_missing_or_stale(session, canvas_id, node_id)
    await _bump_canvas(session, canvas_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{canvas_id}/edges", response_model=EdgeOut, status_code=status.HTTP_201_CREATED)
async def create_edge(
    canvas_id: uuid.UUID,
    payload: EdgeCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> EdgeOut:
    await _require_canvas(session, canvas_id, principal)
    node_ids = {payload.source_node_id, payload.target_node_id}
    found_ids = set(
        (
            await session.scalars(
                select(CanvasNode.id).where(
                    CanvasNode.canvas_id == canvas_id, CanvasNode.id.in_(node_ids)
                )
            )
        ).all()
    )
    if found_ids != node_ids:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "invalid_node_reference",
            "Both edge endpoints must belong to this canvas.",
        )
    edge = Edge(
        canvas_id=canvas_id,
        source_node_id=payload.source_node_id,
        target_node_id=payload.target_node_id,
        kind=payload.kind,
        label=payload.label,
    )
    session.add(edge)
    await _bump_canvas(session, canvas_id)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT, "edge_exists", "That directional edge already exists."
        ) from exc
    await session.refresh(edge)
    return _edge_out(edge)


@router.delete("/{canvas_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge(
    canvas_id: uuid.UUID,
    edge_id: uuid.UUID,
    revision: RevisionQuery,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> Response:
    await _require_canvas(session, canvas_id, principal)
    deleted = await session.scalar(
        delete(Edge)
        .where(Edge.id == edge_id, Edge.canvas_id == canvas_id, Edge.revision == revision)
        .returning(Edge.id)
    )
    if deleted is None:
        exists = await session.scalar(
            select(Edge.id).where(Edge.id == edge_id, Edge.canvas_id == canvas_id)
        )
        if exists is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, "edge_not_found", "Edge not found.")
        raise ApiError(status.HTTP_409_CONFLICT, "revision_conflict", "Edge revision is stale.")
    await _bump_canvas(session, canvas_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{canvas_id}/ai",
    response_model=AIQueryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_ai_rate_limit)],
)
async def ask_ai(
    canvas_id: uuid.UUID,
    payload: AIQuery,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AIQueryOut:
    canvas = await _require_canvas(session, canvas_id, principal)
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_tokens = await session.scalar(
        select(
            func.coalesce(
                func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens),
                0,
            )
        ).where(
            UsageRecord.workspace_id == canvas.workspace_id,
            UsageRecord.created_at >= month_start,
        )
    )
    if int(monthly_tokens or 0) >= settings.monthly_token_budget_per_workspace:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "workspace_token_budget_exhausted",
            "This workspace has reached its monthly AI token budget.",
        )
    selected = (
        await session.scalars(
            select(CanvasNode).where(
                CanvasNode.canvas_id == canvas_id,
                CanvasNode.id.in_(payload.selected_node_ids),
            )
        )
    ).all()
    by_id = {node.id: node for node in selected}
    if set(by_id) != set(payload.selected_node_ids):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "invalid_selected_nodes",
            "Every selected node must belong to this canvas.",
        )

    ordered = [by_id[node_id] for node_id in payload.selected_node_ids]
    document_nodes = [node for node in ordered if node.type == "document"]
    document_node_ids = [node.id for node in document_nodes]
    references = (
        (
            await session.scalars(
                select(CanvasDocumentNode).where(
                    CanvasDocumentNode.canvas_id == canvas_id,
                    CanvasDocumentNode.node_id.in_(document_node_ids),
                )
            )
        ).all()
        if document_node_ids
        else []
    )
    reference_by_node = {reference.node_id: reference for reference in references}
    if len(reference_by_node) != len(document_node_ids):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "document_reference_missing",
            "A selected document node is missing its stored-document reference.",
        )
    document_ids = list(
        dict.fromkeys(reference_by_node[node_id].document_id for node_id in document_node_ids)
    )
    documents = (
        (
            await session.scalars(
                select(Document).where(
                    Document.canvas_id == canvas_id,
                    Document.id.in_(document_ids),
                )
            )
        ).all()
        if document_ids
        else []
    )
    document_by_id = {document.id: document for document in documents}
    if set(document_by_id) != set(document_ids):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "document_not_found",
            "A selected stored document is no longer available.",
        )
    if any(document.status != "ready" for document in documents):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "documents_not_ready",
            "Selected documents must finish processing successfully before querying.",
        )

    note_nodes = [node for node in ordered if node.type != "document"]
    note_ids = [node.id for node in note_nodes]
    context = build_context(
        note_nodes,
        note_ids,
        character_limit=settings.ai_context_character_limit,
    )
    grounded_request = bool(document_ids)
    embedding_provider = build_embedding_provider(settings)
    top_k = settings.document_retrieval_top_k
    threshold = settings.document_relevance_threshold
    candidate_limit = min(max(top_k * 4, 32), 200) if grounded_request else 0
    retrieval_configuration: dict[str, object] = {
        "selectedDocumentIds": [str(document_id) for document_id in document_ids],
        "topK": top_k if grounded_request else 0,
        "threshold": threshold if grounded_request else None,
        "candidateLimit": candidate_limit,
        "embeddingProvider": embedding_provider.name if grounded_request else None,
        "embeddingModel": embedding_provider.model if grounded_request else None,
        "embeddingDimensions": embedding_provider.dimensions if grounded_request else None,
        "embeddingConfigurationVersion": (
            getattr(
                embedding_provider,
                "configuration_version",
                "unspecified-provider-contract-v1",
            )
            if grounded_request
            else None
        ),
    }
    execution_started = datetime.now(UTC)
    execution_started_monotonic = time.perf_counter()
    trace_id = uuid.uuid4()
    request_record = AIRequest(
        trace_id=trace_id,
        user_id=principal.user_id,
        workspace_id=canvas.workspace_id,
        canvas_id=canvas_id,
        instruction=payload.instruction,
        selected_node_ids=[str(node_id) for node_id in payload.selected_node_ids],
        context_snapshot=context.snapshot,
        provider=provider.name,
        model=provider.model,
        status="pending",
        model_configuration=model_configuration(provider, grounded=grounded_request),
        retrieval_configuration=retrieval_configuration,
        prompt_version=(GROUNDED_PROMPT_VERSION if grounded_request else NOTE_PROMPT_VERSION),
        provider_configuration_version=getattr(
            provider, "configuration_version", "unspecified-provider-contract-v1"
        ),
        execution_mode="current_context",
        started_at=execution_started,
    )
    session.add(request_record)
    await session.flush()
    trace_service = TraceService(session)
    await trace_service.start_trace(
        StartTraceInput(
            trace_id=trace_id,
            event_type="ai.execution",
            actor_id=str(principal.user_id),
            actor_type="user",
            user_id=principal.user_id,
            workspace_id=canvas.workspace_id,
            object_id=request_record.id,
            object_type="ai_execution",
            operation="generate_grounded_answer" if grounded_request else "generate_answer",
            metadata={
                "canvasId": str(canvas_id),
                "question": payload.instruction,
                "selectedNodeIds": [str(node_id) for node_id in payload.selected_node_ids],
                "selectedDocumentIds": [str(document_id) for document_id in document_ids],
                "provider": provider.name,
                "model": provider.model,
                "providerConfigurationVersion": getattr(
                    provider,
                    "configuration_version",
                    "unspecified-provider-contract-v1",
                ),
                "promptVersion": request_record.prompt_version,
                "executionMode": request_record.execution_mode,
            },
        )
    )
    execution_nodes: list[AIExecutionNode] = []
    for selected_order, node in enumerate(ordered):
        reference = reference_by_node.get(node.id)
        document = document_by_id.get(reference.document_id) if reference is not None else None
        content_snapshot = node.text
        if document is not None:
            content_snapshot = json.dumps(
                {
                    "documentId": str(document.id),
                    "fileName": document.file_name,
                    "fileType": document.file_type,
                    "mediaType": document.media_type,
                    "contentSha256": document.content_sha256,
                    "status": document.status,
                    "processingStage": document.processing_stage,
                    "pageCount": document.page_count,
                    "chunkCount": document.chunk_count,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        execution_nodes.append(
            AIExecutionNode(
                request_id=request_record.id,
                node_id=node.id,
                selected_order=selected_order,
                node_type=node.type,
                node_revision=node.revision,
                title_snapshot=node.title,
                content_snapshot=content_snapshot,
                document_id=document.id if document is not None else None,
            )
        )
    session.add_all(execution_nodes)
    await session.commit()
    await session.refresh(request_record)

    candidates: list[RetrievedChunk] = []
    if grounded_request:
        try:
            candidates = await search_documents(
                session,
                document_ids=document_ids,
                query=payload.instruction,
                provider=embedding_provider,
                top_k=top_k,
                threshold=threshold,
            )
        except DocumentServiceError as exc:
            completed_at = datetime.now(UTC)
            latency_ms = int((time.perf_counter() - execution_started_monotonic) * 1_000)
            await session.execute(
                update(AIRequest)
                .where(AIRequest.id == request_record.id)
                .values(
                    status="failed",
                    error=exc.safe_message,
                    safe_error_category=exc.code,
                    completed_at=completed_at,
                    latency_ms=latency_ms,
                    updated_at=func.now(),
                )
            )
            await trace_service.fail_trace(
                FailTraceInput(
                    trace_id=trace_id,
                    event_type="ai.execution",
                    actor_id=str(principal.user_id),
                    actor_type="user",
                    user_id=principal.user_id,
                    workspace_id=canvas.workspace_id,
                    object_id=request_record.id,
                    object_type="ai_execution",
                    operation="retrieve_context",
                    metadata={"latencyMs": latency_ms},
                    error=TraceErrorInfo(code=exc.code, message=exc.safe_message),
                )
            )
            await session.commit()
            raise ApiError(exc.status_code, exc.code, exc.safe_message) from exc
        session.add_all(
            AIExecutionChunk(
                request_id=request_record.id,
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                document_version_snapshot=candidate.document_version,
                rank=candidate.rank,
                score=candidate.score,
                included_in_context=candidate.included_in_context,
                exclusion_reason=candidate.exclusion_reason,
                source_id_snapshot=candidate.source_id,
                document_name_snapshot=candidate.document_name,
                content_snapshot=candidate.content,
                page_number_snapshot=candidate.page_number,
                heading_snapshot=candidate.heading,
                char_start_snapshot=candidate.char_start,
                char_end_snapshot=candidate.char_end,
            )
            for candidate in candidates
        )
        included_snapshot = [
            {
                "sourceId": candidate.source_id,
                "documentId": str(candidate.document_id),
                "title": candidate.document_name,
                "text": candidate.content,
            }
            for candidate in candidates
            if candidate.included_in_context
        ]
        request_record.context_snapshot = [*context.snapshot, *included_snapshot]
        await session.commit()

    grounded_sources = [
        GroundedSource(
            source_id=candidate.source_id,
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            document_title=candidate.document_name,
            text=candidate.content,
            page_number=candidate.page_number,
            heading=candidate.heading,
            chunk_index=candidate.chunk_index,
            char_start=candidate.char_start,
            char_end=candidate.char_end,
            score=candidate.score,
            document_version=candidate.document_version,
        )
        for candidate in candidates
        if candidate.included_in_context
    ]
    try:
        if grounded_request:
            if grounded_sources:
                grounded_result = await provider.generate_grounded(
                    payload.instruction,
                    context,
                    grounded_sources,
                )
                grounded_result = validate_grounded_result(grounded_result, grounded_sources)
            else:
                grounded_result = GroundedAIResult(
                    text=(
                        "The selected sources lack sufficient evidence to answer this question. "
                        "Try another question or select a source that contains the needed facts."
                    ),
                    insufficient_evidence=True,
                    citations=[],
                    general_analysis=None,
                    provider_response_id=None,
                )
            response_text = grounded_result.text
            if grounded_result.general_analysis:
                response_text += (
                    "\n\n---\n\n### General analysis (not source-grounded)\n\n"
                    f"{grounded_result.general_analysis}"
                )
            provider_response_id = grounded_result.provider_response_id
            insufficient_evidence = grounded_result.insufficient_evidence
            result_citations = grounded_result.citations
            input_tokens = grounded_result.input_tokens
            output_tokens = grounded_result.output_tokens
            total_tokens = grounded_result.total_tokens
        else:
            result = await provider.generate(payload.instruction, context)
            response_text = result.text
            provider_response_id = result.provider_response_id
            insufficient_evidence = False
            result_citations = []
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
            total_tokens = result.total_tokens
    except AIProviderError as exc:
        completed_at = datetime.now(UTC)
        latency_ms = int((time.perf_counter() - execution_started_monotonic) * 1_000)
        validation_messages = {
            "The AI response cited a source that was not retrieved.",
            "The AI response claimed grounding without a valid citation.",
            "An insufficient-evidence response cannot contain citations.",
            "The AI response did not contain text.",
        }
        safe_provider_message = (
            str(exc)
            if str(exc) in validation_messages
            else "The configured AI provider could not complete the request."
        )
        safe_error_category = (
            "citation_validation_failure" if str(exc) in validation_messages else "provider_failure"
        )
        await session.execute(
            update(AIRequest)
            .where(AIRequest.id == request_record.id)
            .values(
                status="failed",
                error=safe_provider_message,
                safe_error_category=safe_error_category,
                completed_at=completed_at,
                latency_ms=latency_ms,
                updated_at=func.now(),
            )
        )
        await trace_service.fail_trace(
            FailTraceInput(
                trace_id=trace_id,
                event_type="ai.execution",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=canvas.workspace_id,
                object_id=request_record.id,
                object_type="ai_execution",
                operation="call_provider",
                metadata={
                    "provider": provider.name,
                    "model": provider.model,
                    "latencyMs": latency_ms,
                },
                error=TraceErrorInfo(
                    code=safe_error_category,
                    message=safe_provider_message,
                ),
            )
        )
        await session.commit()
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            "ai_provider_error",
            "The AI provider could not complete the request. Try again.",
        ) from exc

    response_x = max(node.position_x + node.width for node in ordered) + 80
    response_y = sum(node.position_y for node in ordered) / len(ordered)
    response_node = CanvasNode(
        canvas_id=canvas_id,
        type="ai_response",
        title=f"AI: {payload.instruction}"[:160],
        text=response_text,
        position_x=response_x,
        position_y=response_y,
        width=380,
        height=260,
    )
    session.add(response_node)
    await session.flush()
    generated_edges = [
        Edge(
            canvas_id=canvas_id,
            source_node_id=node_id,
            target_node_id=response_node.id,
            kind="generated_from",
            label="generated from",
        )
        for node_id in payload.selected_node_ids
    ]
    session.add_all(generated_edges)
    response_record = AIResponse(
        request_id=request_record.id,
        node_id=response_node.id,
        content=response_text,
        provider_response_id=provider_response_id,
        grounded=False,
        insufficient_evidence=insufficient_evidence,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
    session.add(response_record)
    await session.flush()

    source_by_id = {source.source_id: source for source in grounded_sources}
    session.add_all(
        AIExecutionCitation(
            request_id=request_record.id,
            ai_response_id_snapshot=response_record.id,
            ordinal=ordinal,
            source_id_snapshot=result_citation.source_id,
            claim_snapshot=result_citation.claim,
            excerpt_snapshot=source_by_id[result_citation.source_id].text[:1_200],
            document_id_snapshot=source_by_id[result_citation.source_id].document_id,
            document_version_snapshot=source_by_id[result_citation.source_id].document_version,
            chunk_id_snapshot=source_by_id[result_citation.source_id].chunk_id,
            document_name_snapshot=source_by_id[result_citation.source_id].document_title,
            page_number_snapshot=source_by_id[result_citation.source_id].page_number,
            heading_snapshot=source_by_id[result_citation.source_id].heading,
            char_start_snapshot=source_by_id[result_citation.source_id].char_start,
            char_end_snapshot=source_by_id[result_citation.source_id].char_end,
        )
        for ordinal, result_citation in enumerate(result_citations, start=1)
    )
    claims_by_source: dict[str, list[str]] = {}
    citation_order: list[str] = []
    for result_citation in result_citations:
        if result_citation.source_id not in claims_by_source:
            claims_by_source[result_citation.source_id] = []
            citation_order.append(result_citation.source_id)
        claims_by_source[result_citation.source_id].append(result_citation.claim)
    citation_records: list[Citation] = []
    for ordinal, source_id in enumerate(citation_order, start=1):
        source = source_by_id[source_id]
        citation = Citation(
            ai_response_id=response_record.id,
            document_id=source.document_id,
            document_version=source.document_version,
            chunk_id=source.chunk_id,
            identifier=source.source_id,
            claim="\n".join(dict.fromkeys(claims_by_source[source_id]))[:4_000],
            quote=source.text[:1_200],
            ordinal=ordinal,
        )
        session.add(citation)
        citation_records.append(citation)
    response_record.grounded = bool(citation_records) and not insufficient_evidence

    document_node_by_document: dict[uuid.UUID, uuid.UUID] = {}
    for node_id in document_node_ids:
        document_id = reference_by_node[node_id].document_id
        document_node_by_document.setdefault(document_id, node_id)
    cited_document_ids = list(
        dict.fromkeys(source_by_id[source_id].document_id for source_id in citation_order)
    )
    cite_edges = [
        Edge(
            canvas_id=canvas_id,
            source_node_id=response_node.id,
            target_node_id=document_node_by_document[document_id],
            kind="cites",
            label="cites source",
        )
        for document_id in cited_document_ids
    ]
    session.add_all(cite_edges)
    for document_id in cited_document_ids:
        max_relevance_score = max(
            source.score
            for source in source_by_id.values()
            if source.document_id == document_id and source.source_id in claims_by_source
        )
        session.add(
            AIResponseSource(
                ai_response_id=response_record.id,
                document_id=document_id,
                document_node_id=document_node_by_document[document_id],
                max_relevance_score=max_relevance_score,
            )
        )
        for document_node_id in document_node_ids:
            if reference_by_node[document_node_id].document_id != document_id:
                continue
            session.add(
                AIExecutionSource(
                    request_id=request_record.id,
                    response_node_id_snapshot=response_node.id,
                    document_id_snapshot=document_id,
                    document_node_id_snapshot=document_node_id,
                    document_name_snapshot=document_by_id[document_id].file_name,
                    max_relevance_score=max_relevance_score,
                )
            )
    edges = [*generated_edges, *cite_edges]
    completed_at = datetime.now(UTC)
    latency_ms = int((time.perf_counter() - execution_started_monotonic) * 1_000)
    input_token_count = input_tokens or 0
    output_token_count = output_tokens or 0
    estimated_cost = (
        input_token_count * settings.estimated_input_cost_per_million_tokens
        + output_token_count * settings.estimated_output_cost_per_million_tokens
    ) / 1_000_000
    if insufficient_evidence:
        session.add(
            AIClaim(
                request_id=request_record.id,
                ai_response_id=response_record.id,
                ordinal=1,
                claim=response_text[:4_000],
                evidence_status="insufficient_evidence",
                evidence_snapshot=[],
            )
        )
    elif result_citations:
        session.add_all(
            AIClaim(
                request_id=request_record.id,
                ai_response_id=response_record.id,
                ordinal=ordinal,
                claim=result_citation.claim,
                evidence_status="supported",
                evidence_snapshot=[
                    {
                        "sourceId": result_citation.source_id,
                        "documentId": str(source_by_id[result_citation.source_id].document_id),
                        "documentVersion": source_by_id[result_citation.source_id].document_version,
                        "chunkId": str(source_by_id[result_citation.source_id].chunk_id),
                    }
                ],
            )
            for ordinal, result_citation in enumerate(result_citations, start=1)
        )
    else:
        session.add(
            AIClaim(
                request_id=request_record.id,
                ai_response_id=response_record.id,
                ordinal=1,
                claim=response_text[:4_000],
                evidence_status="inference",
                evidence_snapshot=[],
            )
        )
    session.add(
        UsageRecord(
            user_id=principal.user_id,
            workspace_id=canvas.workspace_id,
            operation="ai_execution",
            input_tokens=input_token_count,
            output_tokens=output_token_count,
            estimated_cost_usd=estimated_cost,
            metadata_payload={
                "provider": provider.name,
                "model": provider.model,
                "requestId": str(request_record.id),
            },
        )
    )
    await session.execute(
        update(AIRequest)
        .where(AIRequest.id == request_record.id)
        .values(
            status="completed",
            error=None,
            completed_at=completed_at,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost,
            updated_at=func.now(),
        )
    )
    await trace_service.complete_trace(
        CompleteTraceInput(
            trace_id=trace_id,
            event_type="ai.execution",
            actor_id=str(principal.user_id),
            actor_type="user",
            user_id=principal.user_id,
            workspace_id=canvas.workspace_id,
            object_id=request_record.id,
            object_type="ai_execution",
            operation="complete_execution",
            metadata={
                "requestId": str(request_record.id),
                "responseId": str(response_record.id),
                "responseNodeId": str(response_node.id),
                "executionMode": request_record.execution_mode,
                "retrievedChunks": [
                    {
                        "sourceId": candidate.source_id,
                        "documentId": str(candidate.document_id),
                        "documentVersion": candidate.document_version,
                        "chunkId": str(candidate.chunk_id),
                        "rank": candidate.rank,
                        "score": candidate.score,
                        "included": candidate.included_in_context,
                        "exclusionReason": candidate.exclusion_reason,
                    }
                    for candidate in candidates
                ],
                "citations": [
                    {
                        "sourceId": citation.source_id,
                        "claim": citation.claim,
                    }
                    for citation in result_citations
                ],
                "citationValidation": "passed",
                "insufficientEvidence": insufficient_evidence,
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": total_tokens,
                "latencyMs": latency_ms,
                "estimatedCostUsd": estimated_cost,
            },
        )
    )
    await _bump_canvas(session, canvas_id)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        failed_at = datetime.now(UTC)
        await session.execute(
            update(AIRequest)
            .where(AIRequest.id == request_record.id)
            .values(
                status="failed",
                error="Could not persist the AI response.",
                safe_error_category="persistence_conflict",
                completed_at=failed_at,
                latency_ms=latency_ms,
                updated_at=func.now(),
            )
        )
        await TraceService(session).fail_trace(
            FailTraceInput(
                trace_id=trace_id,
                event_type="ai.execution",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=canvas.workspace_id,
                object_id=request_record.id,
                object_type="ai_execution",
                operation="persist_execution",
                metadata={"latencyMs": latency_ms},
                error=TraceErrorInfo(
                    code="persistence_conflict",
                    message="The execution could not be persisted because its canvas changed.",
                ),
            )
        )
        await session.commit()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "ai_response_conflict",
            "The canvas changed while the AI response was being saved.",
        ) from exc
    await session.refresh(response_node)
    await session.refresh(response_record)
    for citation in citation_records:
        await session.refresh(citation)
    for edge in edges:
        await session.refresh(edge)
    citation_outputs = [
        CitationOut(
            id=citation.id,
            source_id=citation.identifier,
            document_id=citation.document_id,
            document_title=document_by_id[citation.document_id].file_name,
            chunk_id=citation.chunk_id,
            page_number=source_by_id[citation.identifier].page_number,
            heading=source_by_id[citation.identifier].heading,
            chunk_index=source_by_id[citation.identifier].chunk_index,
            start_offset=source_by_id[citation.identifier].char_start,
            end_offset=source_by_id[citation.identifier].char_end,
            excerpt=citation.quote,
            claim=citation.claim,
            ordinal=citation.ordinal,
        )
        for citation in citation_records
    ]
    return AIQueryOut(
        request_id=request_record.id,
        response_id=response_record.id,
        trace_id=trace_id,
        node=node_out(response_node, citations=citation_outputs),
        edges=[_edge_out(edge) for edge in edges],
        mock=provider.mock,
        grounded=response_record.grounded,
        insufficient_evidence=response_record.insufficient_evidence,
        citations=citation_outputs,
    )
