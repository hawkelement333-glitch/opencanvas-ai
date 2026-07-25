from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.graph_retrieval_schemas import (
    ApaCitationOut,
    ApaRenderOut,
    EvidenceBundleOut,
    EvidenceBundleRequest,
    GraphRetrievalOut,
    RetrievalCitationOut,
    RetrievalDecisionOut,
    RetrievalTraceSummaryOut,
    StartGraphRetrievalIn,
)
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.documents.embeddings import build_embedding_provider
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.graph_retrieval import (
    APA_RENDERER_VERSION,
    GraphAwareRetrievalService,
    GraphRetrievalConflictError,
    GraphRetrievalError,
    GraphRetrievalNotFoundError,
    GraphRetrievalValidationError,
    RetrievalRecord,
    StartGraphRetrieval,
    TraceEvidenceBundleService,
)
from opencanvas_api.services.trace import TraceService

router = APIRouter(prefix="/workspaces/{workspace_id}/canvases/{canvas_id}")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _error(error: GraphRetrievalError) -> ApiError:
    if isinstance(error, GraphRetrievalNotFoundError):
        return ApiError(status.HTTP_404_NOT_FOUND, error.code, error.safe_message)
    if isinstance(error, GraphRetrievalConflictError):
        return ApiError(status.HTTP_409_CONFLICT, error.code, error.safe_message)
    if isinstance(error, GraphRetrievalValidationError):
        return ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.safe_message)
    return ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, error.code, error.safe_message)


def _service(session: AsyncSession, settings: Settings) -> GraphAwareRetrievalService:
    return GraphAwareRetrievalService(
        session,
        embedding_provider=build_embedding_provider(settings),
    )


@router.post("/graph-retrievals", response_model=GraphRetrievalOut)
async def start_retrieval(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: StartGraphRetrievalIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> GraphRetrievalOut:
    try:
        record = await _service(session, settings).retrieve(
            StartGraphRetrieval(
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                query=payload.query,
                selected_object_ids=payload.selected_object_ids,
                seed_object_ids=payload.seed_object_ids,
                idempotency_key=payload.idempotency_key,
                max_depth=payload.max_depth,
                top_k=payload.top_k,
                min_relevance=payload.min_relevance,
            )
        )
        await session.commit()
    except GraphRetrievalError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _out(record)


@router.get("/graph-retrievals/{retrieval_id}", response_model=GraphRetrievalOut)
async def get_retrieval(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    retrieval_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> GraphRetrievalOut:
    return _out(
        await _owned(_service(session, settings), principal, workspace_id, canvas_id, retrieval_id)
    )


@router.get(
    "/graph-retrievals/{retrieval_id}/citations",
    response_model=list[RetrievalCitationOut],
)
async def get_citations(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    retrieval_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> list[RetrievalCitationOut]:
    record = await _owned(
        _service(session, settings), principal, workspace_id, canvas_id, retrieval_id
    )
    return [_citation(item) for item in record.citations]


@router.get(
    "/graph-retrievals/{retrieval_id}/trace",
    response_model=RetrievalTraceSummaryOut,
)
async def get_trace_summary(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    retrieval_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> RetrievalTraceSummaryOut:
    record = await _owned(
        _service(session, settings), principal, workspace_id, canvas_id, retrieval_id
    )
    events = await TraceService(session).get_trace(record.run.trace_id)
    return RetrievalTraceSummaryOut(
        trace_id=record.run.trace_id,
        statuses=[event.status for event in events],
        event_types=[event.event_type for event in events],
        safe_metadata=[event.metadata_payload for event in events],
    )


@router.post(
    "/graph-retrievals/{retrieval_id}/citations/render",
    response_model=ApaRenderOut,
)
async def render_citations(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    retrieval_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ApaRenderOut:
    service = _service(session, settings)
    record = await _owned(service, principal, workspace_id, canvas_id, retrieval_id)
    try:
        rendered = await service.render_apa(record, user_id=principal.user_id)
        await session.commit()
    except GraphRetrievalError as exc:
        await session.commit()
        raise _error(exc) from exc
    return ApaRenderOut(
        renderer_version=APA_RENDERER_VERSION,
        citations=[
            ApaCitationOut(
                citation_id=item.citation_id,
                in_text=item.in_text,
                reference=item.reference,
            )
            for item in rendered
        ],
    )


@router.post(
    "/graph-retrievals/{retrieval_id}/evidence-bundle",
    response_model=EvidenceBundleOut,
)
async def generate_bundle(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    retrieval_id: uuid.UUID,
    payload: EvidenceBundleRequest,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> EvidenceBundleOut:
    service = _service(session, settings)
    record = await _owned(service, principal, workspace_id, canvas_id, retrieval_id)
    if payload.include_authorized_sources:
        bundle_id = uuid.uuid5(retrieval_id, "trace-evidence-bundle-v1")
        await DomainEventService(session).record(
            CreateDomainEvent(
                event_type="evidence.bundle.export_denied",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                subject_id=bundle_id,
                related_id=retrieval_id,
                actor_user_id=principal.user_id,
                source_identity=f"{bundle_id}:export-denied",
                trace_id=record.run.trace_id,
                payload={
                    "retrievalId": str(retrieval_id),
                    "bundleState": "export_denied",
                    "failureCode": "export_not_authorized",
                },
                origin_type="authenticated_user",
            )
        )
        await session.commit()
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "source_export_not_authorized",
            "Complete source export is not authorized.",
        )
    try:
        bundle = await TraceEvidenceBundleService(session).generate(
            record,
            user_id=principal.user_id,
        )
        await session.commit()
    except GraphRetrievalError as exc:
        await session.rollback()
        bundle_id = uuid.uuid5(retrieval_id, "trace-evidence-bundle-v1")
        await DomainEventService(session).record(
            CreateDomainEvent(
                event_type="evidence.bundle.failed",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                subject_id=bundle_id,
                related_id=retrieval_id,
                actor_user_id=principal.user_id,
                source_identity=f"{bundle_id}:failed",
                trace_id=record.run.trace_id,
                payload={
                    "retrievalId": str(retrieval_id),
                    "bundleState": "failed",
                    "failureCode": exc.code,
                },
                origin_type="authenticated_user",
            )
        )
        await session.commit()
        raise _error(exc) from exc
    return _bundle(bundle)


@router.get(
    "/evidence-bundles/{bundle_id}",
    response_model=EvidenceBundleOut,
)
async def get_bundle(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    bundle_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> EvidenceBundleOut:
    try:
        bundle = await TraceEvidenceBundleService(session).get_owned(
            bundle_id=bundle_id,
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
        )
    except GraphRetrievalError as exc:
        raise _error(exc) from exc
    return _bundle(bundle)


@router.post("/evidence-bundles/{bundle_id}/download")
async def download_bundle(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    bundle_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> Response:
    try:
        bundle = await TraceEvidenceBundleService(session).get_owned(
            bundle_id=bundle_id,
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
        )
        await DomainEventService(session).record(
            CreateDomainEvent(
                event_type="evidence.bundle.accessed",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                subject_id=bundle_id,
                related_id=bundle.retrieval_id,
                actor_user_id=principal.user_id,
                source_identity=f"{bundle_id}:accessed",
                trace_id=bundle.trace_id,
                payload={
                    "retrievalId": str(bundle.retrieval_id),
                    "bundleState": "accessed",
                },
                origin_type="authenticated_user",
            )
        )
        await session.commit()
    except GraphRetrievalError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return Response(
        content=bundle.artifact_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="trace-evidence-bundle.zip"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _owned(
    service: GraphAwareRetrievalService,
    principal: Principal,
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    retrieval_id: uuid.UUID,
) -> RetrievalRecord:
    try:
        return await service.get_owned(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            retrieval_id=retrieval_id,
        )
    except GraphRetrievalError as exc:
        raise _error(exc) from exc


def _out(record: RetrievalRecord) -> GraphRetrievalOut:
    run = record.run
    return GraphRetrievalOut(
        retrieval_id=run.retrieval_id,
        workspace_id=run.workspace_id,
        canvas_id=run.canvas_id,
        query=run.query_text,
        selected_object_ids=[uuid.UUID(value) for value in run.selected_object_ids],
        seed_object_ids=[uuid.UUID(value) for value in run.seed_object_ids],
        graph_revision=run.graph_revision,
        algorithm_version=run.algorithm_version,
        schema_version=run.schema_version,
        mode=run.mode,
        outcome=run.outcome,
        bounded=run.bounded,
        trace_id=run.trace_id,
        created_at=run.created_at,
        duplicate=record.duplicate,
        decisions=[
            RetrievalDecisionOut(
                decision_id=item.decision_id,
                object_id=item.object_id,
                relationship_id=item.relationship_id,
                included=item.included,
                reason_code=item.reason_code,
                distance=item.distance,
                rank=item.rank,
                score=item.score,
                relationship_path=[uuid.UUID(value) for value in item.relationship_path],
            )
            for item in record.decisions
        ],
        citations=[_citation(item) for item in record.citations],
    )


def _citation(item: object) -> RetrievalCitationOut:
    from opencanvas_api.db.models import GraphRetrievalCitation

    if not isinstance(item, GraphRetrievalCitation):
        raise TypeError("citation serializer received an unsupported object")
    return RetrievalCitationOut(
        citation_id=item.citation_id,
        canonical_object_id=item.canonical_object_id,
        canonical_version=item.canonical_version,
        source_version=item.source_version,
        source_sha256=item.source_sha256,
        source_title=item.source_title,
        source_type=item.source_type,
        passage_identity=item.passage_identity,
        excerpt=item.excerpt,
        excerpt_sha256=item.excerpt_sha256,
        locator=item.locator,
        relationship_path=[uuid.UUID(value) for value in item.relationship_path],
        graph_revision=item.graph_revision,
        ordinal=item.ordinal,
        citation_schema_version=item.citation_schema_version,
        trace_id=item.trace_id,
    )


def _bundle(item: object) -> EvidenceBundleOut:
    from opencanvas_api.db.models import TraceEvidenceBundle

    if not isinstance(item, TraceEvidenceBundle):
        raise TypeError("bundle serializer received an unsupported object")
    return EvidenceBundleOut(
        bundle_id=item.bundle_id,
        retrieval_id=item.retrieval_id,
        schema_version=item.schema_version,
        state=item.state,
        artifact_sha256=item.artifact_sha256,
        byte_size=item.byte_size,
        manifest=item.manifest,
        trace_id=item.trace_id,
        created_at=item.created_at,
    )


__all__ = ["router"]
