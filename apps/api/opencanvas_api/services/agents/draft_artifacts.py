from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import DraftArtifactSave, NodeOut
from opencanvas_api.api.serialization import draft_provenance_for_nodes, node_out
from opencanvas_api.db.models import (
    AIRequest,
    AIResponse,
    Canvas,
    CanvasNode,
    ControlledDraftArtifact,
    Edge,
    Workspace,
)


async def save_draft_artifact(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    payload: DraftArtifactSave,
) -> NodeOut:
    # Lock the source execution to serialize concurrent saves without changing its evidence.
    request = await session.scalar(
        select(AIRequest)
        .join(Canvas, Canvas.id == AIRequest.canvas_id)
        .join(Workspace, Workspace.id == Canvas.workspace_id)
        .where(
            AIRequest.id == execution_id,
            AIRequest.user_id == user_id,
            AIRequest.workspace_id == workspace_id,
            AIRequest.canvas_id == payload.canvas_id,
            Canvas.workspace_id == workspace_id,
            Workspace.owner_id == user_id,
            Workspace.deleted_at.is_(None),
            Workspace.lifecycle_state != "deleted",
            AIRequest.execution_mode == "controlled_immutable_context",
        )
        .with_for_update(of=AIRequest)
    )
    if request is None:
        raise ApiError(404, "draft_not_found", "Controlled draft not found.")
    if request.status != "completed":
        raise ApiError(409, "draft_not_completed", "Only a completed draft can be saved.")
    response = await session.scalar(select(AIResponse).where(AIResponse.request_id == request.id))
    if response is None:
        raise ApiError(409, "draft_result_unavailable", "Original draft evidence is unavailable.")
    saved = await session.get(ControlledDraftArtifact, execution_id)
    if saved is not None:
        return await _saved_node(session, saved, request, response)

    node = CanvasNode(
        id=uuid.uuid4(),
        canvas_id=request.canvas_id,
        type="ai_response",
        title="Saved AI draft",
        text=response.content,
        position_x=payload.position.x,
        position_y=payload.position.y,
        width=360,
        height=280,
    )
    saved = ControlledDraftArtifact(
        execution_id=request.id,
        response_id=response.id,
        trace_id=request.trace_id,
        user_id=user_id,
        workspace_id=workspace_id,
        canvas_id=request.canvas_id,
        node_id=node.id,
    )
    try:
        # Identity, node, edges and canvas revision form one transaction. No source writes.
        session.add(node)
        await session.flush()
        session.add(saved)
        await session.flush()
        selected = [uuid.UUID(value) for value in request.selected_node_ids]
        existing = (
            await session.scalars(
                select(CanvasNode.id).where(
                    CanvasNode.canvas_id == request.canvas_id, CanvasNode.id.in_(selected)
                )
            )
        ).all()
        for source_id in existing:
            session.add(
                Edge(
                    canvas_id=request.canvas_id,
                    source_node_id=source_id,
                    target_node_id=node.id,
                    kind="generated_from",
                )
            )
        await session.execute(
            update(Canvas)
            .where(Canvas.id == request.canvas_id)
            .values(revision=Canvas.revision + 1, updated_at=func.now())
        )
        await session.commit()
    except IntegrityError:
        # SQLite or a uniqueness race may not honor row locking; reconcile the winner.
        await session.rollback()
        winner = await session.get(ControlledDraftArtifact, execution_id)
        if winner is None:
            raise
        return await save_draft_artifact(
            session,
            user_id=user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            payload=payload,
        )
    await session.refresh(node)
    provenance = await draft_provenance_for_nodes(session, [node])
    return node_out(node, draft_provenance=provenance.get(node.id))


async def _saved_node(
    session: AsyncSession,
    saved: ControlledDraftArtifact,
    request: AIRequest,
    response: AIResponse,
) -> NodeOut:
    if (saved.user_id, saved.workspace_id, saved.canvas_id, saved.response_id, saved.trace_id) != (
        request.user_id,
        request.workspace_id,
        request.canvas_id,
        response.id,
        request.trace_id,
    ):
        raise ApiError(409, "draft_identity_conflict", "Saved draft identity does not match.")
    node = await session.scalar(
        select(CanvasNode).where(
            CanvasNode.id == saved.node_id,
            CanvasNode.canvas_id == saved.canvas_id,
        )
    )
    if node is None:
        raise ApiError(409, "draft_artifact_deleted", "The saved artifact was deleted.")
    provenance = await draft_provenance_for_nodes(session, [node])
    return node_out(node, draft_provenance=provenance.get(node.id))
