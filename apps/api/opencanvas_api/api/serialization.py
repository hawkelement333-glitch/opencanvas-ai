from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.schemas import (
    CitationOut,
    DocumentFileType,
    DocumentMetadata,
    DocumentProcessingStage,
    DocumentStatus,
    NodeOut,
    NodeType,
    Point,
    SourcePassageOut,
)
from opencanvas_api.db.models import (
    AIResponse,
    CanvasDocumentNode,
    CanvasNode,
    Citation,
    Document,
    DocumentChunk,
)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def document_metadata_out(document: Document) -> DocumentMetadata:
    return DocumentMetadata(
        id=document.id,
        canvas_id=document.canvas_id,
        file_name=document.file_name,
        file_type=cast(DocumentFileType, document.file_type),
        media_type=document.media_type,
        file_size=document.file_size_bytes,
        page_count=document.page_count,
        status=cast(DocumentStatus, document.status),
        processing_stage=cast(DocumentProcessingStage, document.processing_stage),
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        created_at=utc(document.created_at),
        updated_at=utc(document.updated_at),
    )


def citation_out(citation: Citation, chunk: DocumentChunk, document: Document) -> CitationOut:
    return CitationOut(
        id=citation.id,
        source_id=citation.identifier,
        document_id=citation.document_id,
        document_title=document.file_name,
        chunk_id=citation.chunk_id,
        page_number=chunk.page_number,
        heading=chunk.heading,
        chunk_index=chunk.chunk_index,
        start_offset=chunk.char_start,
        end_offset=chunk.char_end,
        excerpt=citation.quote,
        claim=citation.claim,
        ordinal=citation.ordinal,
    )


def source_passage_out(chunk: DocumentChunk, document: Document) -> SourcePassageOut:
    return SourcePassageOut(
        document_id=document.id,
        chunk_id=chunk.id,
        document_title=document.file_name,
        page_number=chunk.page_number,
        heading=chunk.heading,
        chunk_index=chunk.chunk_index,
        start_offset=chunk.char_start,
        end_offset=chunk.char_end,
        text=chunk.content,
    )


def node_out(
    node: CanvasNode,
    *,
    document: DocumentMetadata | None = None,
    citations: list[CitationOut] | None = None,
) -> NodeOut:
    return NodeOut(
        id=node.id,
        canvas_id=node.canvas_id,
        type=cast(NodeType, node.type),
        title=node.title,
        text=node.text,
        position=Point(x=node.position_x, y=node.position_y),
        width=node.width,
        height=node.height,
        revision=node.revision,
        created_at=utc(node.created_at),
        updated_at=utc(node.updated_at),
        document=document,
        citations=citations or [],
    )


async def enrich_nodes(
    session: AsyncSession, nodes: Sequence[CanvasNode]
) -> tuple[dict[uuid.UUID, DocumentMetadata], dict[uuid.UUID, list[CitationOut]]]:
    node_ids = [node.id for node in nodes]
    if not node_ids:
        return {}, {}

    references = (
        await session.scalars(
            select(CanvasDocumentNode).where(CanvasDocumentNode.node_id.in_(node_ids))
        )
    ).all()
    document_ids = {reference.document_id for reference in references}
    documents = (
        (await session.scalars(select(Document).where(Document.id.in_(document_ids)))).all()
        if document_ids
        else []
    )
    documents_by_id = {document.id: document for document in documents}
    document_by_node = {
        reference.node_id: document_metadata_out(documents_by_id[reference.document_id])
        for reference in references
        if reference.document_id in documents_by_id
    }

    responses = (
        await session.scalars(select(AIResponse).where(AIResponse.node_id.in_(node_ids)))
    ).all()
    response_node_by_id = {
        response.id: response.node_id for response in responses if response.node_id is not None
    }
    citations_by_node: dict[uuid.UUID, list[CitationOut]] = {}
    if response_node_by_id:
        rows = (
            await session.execute(
                select(Citation, DocumentChunk, Document)
                .join(DocumentChunk, DocumentChunk.id == Citation.chunk_id)
                .join(Document, Document.id == Citation.document_id)
                .where(Citation.ai_response_id.in_(response_node_by_id))
                .order_by(Citation.ai_response_id, Citation.ordinal, Citation.id)
            )
        ).all()
        for citation, chunk, document in rows:
            node_id = response_node_by_id[citation.ai_response_id]
            citations_by_node.setdefault(node_id, []).append(
                citation_out(citation, chunk, document)
            )
    return document_by_node, citations_by_node
