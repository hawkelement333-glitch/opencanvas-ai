from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    Document,
    DocumentChunk,
    DocumentEmbedding,
    DocumentVersion,
    IngestionRequest,
    MalwareScanResult,
    ObjectPromotion,
    RetrievalHead,
    StorageObjectLifecycleTransition,
    StorageObjectVersion,
)
from opencanvas_api.services.documents.embeddings import EmbeddingProvider


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    file_type: str
    content: str
    page_number: int | None
    heading: str | None
    chunk_index: int
    char_start: int
    char_end: int
    score: float
    rank: int = 0
    included_in_context: bool = True
    exclusion_reason: str | None = None
    document_version: int = 1

    @property
    def source_id(self) -> str:
        return f"chunk_{self.chunk_id.hex}"


async def search_documents(
    session: AsyncSession,
    *,
    document_ids: list[uuid.UUID] | tuple[uuid.UUID, ...],
    query: str,
    provider: EmbeddingProvider,
    top_k: int,
    threshold: float,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    selected_ids = tuple(dict.fromkeys(document_ids))
    if not selected_ids or not query.strip():
        return []
    query_vector = (await provider.embed([query]))[0]
    candidate_limit = min(max(top_k * 4, 32), 200)
    if session.get_bind().dialect.name == "postgresql":
        candidates = await _search_postgresql(
            session,
            document_ids=selected_ids,
            query_vector=query_vector,
            provider=provider,
            candidate_limit=candidate_limit,
            settings=settings,
        )
    else:
        candidates = await _search_in_memory(
            session,
            document_ids=selected_ids,
            query_vector=query_vector,
            provider=provider,
            candidate_limit=candidate_limit,
            settings=settings,
        )
    ranked: list[RetrievedChunk] = []
    for rank, candidate in enumerate(candidates, start=1):
        included = rank <= top_k and candidate.score >= threshold
        reason: str | None = None
        if candidate.score < threshold:
            reason = "below_relevance_threshold"
        elif rank > top_k:
            reason = "top_k_limit"
        ranked.append(
            replace(
                candidate,
                rank=rank,
                included_in_context=included,
                exclusion_reason=reason,
            )
        )
    return ranked


async def _search_postgresql(
    session: AsyncSession,
    *,
    document_ids: tuple[uuid.UUID, ...],
    query_vector: list[float],
    provider: EmbeddingProvider,
    candidate_limit: int,
    settings: Settings | None,
) -> list[RetrievedChunk]:
    embedding_column = cast(Any, DocumentEmbedding.embedding)
    distance = embedding_column.cosine_distance(query_vector)
    statement = (
        select(DocumentChunk, Document.file_name, Document.file_type, distance.label("distance"))
        .join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .outerjoin(RetrievalHead, RetrievalHead.document_id == Document.id)
        .where(
            DocumentChunk.document_id.in_(document_ids),
            _published_or_legacy_without_request(settings),
            Document.status == "ready",
            DocumentEmbedding.model == provider.model,
        )
        .order_by(distance.asc())
        .limit(candidate_limit)
    )
    rows = (await session.execute(statement)).all()
    return [
        _retrieved(chunk, document_name, file_type, 1.0 - float(distance_value))
        for chunk, document_name, file_type, distance_value in rows
    ]


async def _search_in_memory(
    session: AsyncSession,
    *,
    document_ids: tuple[uuid.UUID, ...],
    query_vector: list[float],
    provider: EmbeddingProvider,
    candidate_limit: int,
    settings: Settings | None,
) -> list[RetrievedChunk]:
    statement = (
        select(DocumentChunk, Document.file_name, Document.file_type, DocumentEmbedding.embedding)
        .join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .outerjoin(RetrievalHead, RetrievalHead.document_id == Document.id)
        .where(
            DocumentChunk.document_id.in_(document_ids),
            _published_or_legacy_without_request(settings),
            Document.status == "ready",
            DocumentEmbedding.model == provider.model,
        )
    )
    rows = (await session.execute(statement)).all()
    scored = [
        _retrieved(
            chunk,
            document_name,
            file_type,
            _cosine_similarity(query_vector, [float(value) for value in embedding]),
        )
        for chunk, document_name, file_type, embedding in rows
    ]
    scored.sort(key=lambda item: (-item.score, item.chunk_index, item.chunk_id.hex))
    return scored[:candidate_limit]


def _retrieved(
    chunk: DocumentChunk, document_name: str, file_type: str, score: float
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        document_name=document_name,
        file_type=file_type,
        content=chunk.content,
        page_number=chunk.page_number,
        heading=chunk.heading,
        chunk_index=chunk.chunk_index,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        score=max(-1.0, min(1.0, score)),
        document_version=chunk.document_version,
    )


def _published_or_legacy_without_request(settings: Settings | None) -> ColumnElement[bool]:
    if settings is not None and settings.object_ingestion_mode != "disabled":
        latest_sequence = (
            select(func.max(StorageObjectLifecycleTransition.sequence))
            .where(
                StorageObjectLifecycleTransition.object_version_id
                == StorageObjectVersion.object_version_id
            )
            .correlate(StorageObjectVersion)
            .scalar_subquery()
        )
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.malware_scan_result_max_age_seconds)
        return and_(
            RetrievalHead.document_id.is_not(None),
            exists(
                select(StorageObjectVersion.object_version_id)
                .join(
                    DocumentVersion,
                    DocumentVersion.id == StorageObjectVersion.document_version_id,
                )
                .join(
                    ObjectPromotion,
                    ObjectPromotion.target_object_version_id
                    == StorageObjectVersion.object_version_id,
                )
                .join(
                    MalwareScanResult,
                    MalwareScanResult.scan_result_id == ObjectPromotion.scan_result_id,
                )
                .join(
                    StorageObjectLifecycleTransition,
                    (
                        StorageObjectLifecycleTransition.object_version_id
                        == StorageObjectVersion.object_version_id
                    )
                    & (StorageObjectLifecycleTransition.sequence == latest_sequence),
                )
                .where(
                    DocumentVersion.document_id == Document.id,
                    DocumentVersion.version == Document.current_version,
                    StorageObjectVersion.security_class == "clean",
                    StorageObjectVersion.content_sha256 == DocumentVersion.content_sha256,
                    StorageObjectLifecycleTransition.current_state == "clean",
                    MalwareScanResult.outcome == "clean",
                    MalwareScanResult.scanner_identity == settings.malware_scanner_identity,
                    MalwareScanResult.scanner_version == settings.malware_scanner_version,
                    MalwareScanResult.policy_version == settings.malware_policy_version,
                    MalwareScanResult.scanned_at >= cutoff,
                )
            ),
        )
    return or_(
        RetrievalHead.document_id.is_not(None),
        ~exists(
            select(IngestionRequest.request_id).where(IngestionRequest.document_id == Document.id)
        ),
    )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return -1.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
