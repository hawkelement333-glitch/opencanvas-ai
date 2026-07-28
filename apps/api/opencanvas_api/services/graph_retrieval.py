from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    CanonicalCanvasObjectBinding,
    CanonicalDocument,
    CanonicalGraphEntity,
    CanonicalGraphRelationship,
    CanonicalNote,
    CanonicalObject,
    CanonicalRelationship,
    CanonicalRelationshipHistory,
    Canvas,
    DocumentVersion,
    GraphRetrievalCitation,
    GraphRetrievalDecision,
    GraphRetrievalRun,
    TraceEvidenceBundle,
    Workspace,
    WorkspaceGraphState,
)
from opencanvas_api.services.documents.embeddings import EmbeddingProvider
from opencanvas_api.services.documents.retrieval import RetrievedChunk, search_documents
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    FailTraceInput,
    StartTraceInput,
    TraceContext,
    TraceErrorInfo,
    TracePersistenceError,
    TraceService,
)

RETRIEVAL_ALGORITHM_VERSION = "graph-retrieval-v1"
RETRIEVAL_SCHEMA_VERSION = "graph-retrieval-result-v1"
CITATION_SCHEMA_VERSION = "graph-citation-v1"
APA_RENDERER_VERSION = "apa7-repository-sources-v1"
BUNDLE_SCHEMA_VERSION = "trace-evidence-bundle-v1"
MAX_SEEDS = 50
MAX_SELECTED = 50
MAX_DEPTH = 3
MAX_ENTITIES = 250
MAX_RELATIONSHIPS = 500
MAX_CANDIDATES = 200
MAX_PASSAGES = 50
MAX_RESPONSE_CHARACTERS = 60_000
MAX_QUERY_CHARACTERS = 4_000
MAX_BUNDLE_BYTES = 5 * 1024 * 1024
MAX_BUNDLE_FILES = 100

RetrievalOutcome = Literal[
    "supported",
    "conflicting_evidence",
    "insufficient_evidence",
    "bounded_result",
]

INCLUSION_REASONS = frozenset(
    {
        "selected_seed",
        "direct_citation",
        "supporting_relationship",
        "reference_relationship",
        "derivation_relationship",
        "graph_related_candidate",
        "exact_source_passage_match",
        "approved_deterministic_fallback",
    }
)
EXCLUSION_REASONS = frozenset(
    {
        "outside_selected_context",
        "unauthorized_scope",
        "inactive_relationship",
        "superseded_relationship",
        "invalid_relationship_direction",
        "unsupported_relationship_kind",
        "historical_resource",
        "removed_resource",
        "missing_immutable_version",
        "missing_source_content",
        "malformed_locator",
        "duplicate_candidate",
        "candidate_limit_reached",
        "traversal_limit_reached",
        "insufficient_relevance",
        "unsupported_schema_version",
        "conflicting_provenance",
        "unsafe_source",
        "export_not_authorized",
    }
)
RETRIEVAL_OUTCOMES = frozenset(
    {"supported", "conflicting_evidence", "insufficient_evidence", "bounded_result"}
)
RELATIONSHIP_DIRECTIONS: dict[str, Literal["forward", "both"]] = {
    "references": "forward",
    "derived_from": "forward",
    "related_to": "both",
    "cites": "forward",
    "supports": "forward",
    "contradicts": "both",
    "produced_by": "forward",
    "affected_by": "forward",
}


class GraphRetrievalError(RuntimeError):
    code = "graph_retrieval_failed"
    safe_message = "Graph-aware retrieval could not be completed."


class GraphRetrievalValidationError(GraphRetrievalError):
    code = "graph_retrieval_invalid"
    safe_message = "The graph-aware retrieval request is invalid."


class GraphRetrievalNotFoundError(GraphRetrievalError):
    code = "graph_retrieval_not_found"
    safe_message = "Retrieval result not found."


class GraphRetrievalConflictError(GraphRetrievalError):
    code = "graph_retrieval_conflict"
    safe_message = "The retrieval request conflicts with existing evidence."


class GraphRetrievalStorageError(GraphRetrievalError):
    code = "graph_retrieval_storage_failed"
    safe_message = "Retrieval evidence is temporarily unavailable."


@dataclass(frozen=True, slots=True)
class StartGraphRetrieval:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    query: str
    selected_object_ids: tuple[uuid.UUID, ...]
    seed_object_ids: tuple[uuid.UUID, ...]
    idempotency_key: str
    max_depth: int = 2
    top_k: int = 8
    min_relevance: float = 0.15


@dataclass(frozen=True, slots=True)
class RetrievalRecord:
    run: GraphRetrievalRun
    decisions: tuple[GraphRetrievalDecision, ...]
    citations: tuple[GraphRetrievalCitation, ...]
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ApaCitation:
    citation_id: uuid.UUID
    in_text: str
    reference: str


@dataclass(frozen=True, slots=True)
class _Entity:
    object: CanonicalObject
    title: str
    text: str | None
    source_type: str
    legacy_document_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class _Passage:
    object_id: uuid.UUID
    title: str
    source_type: str
    canonical_version: int
    source_version: int
    source_sha256: str
    passage_identity: str
    excerpt: str
    locator: dict[str, object]
    score: float
    distance: int
    path: tuple[uuid.UUID, ...]


class GraphAwareRetrievalService:
    """Selected-context graph traversal and immutable exact-evidence boundary."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        embedding_provider: EmbeddingProvider,
        settings: Settings | None = None,
        trace_service: TraceService | None = None,
        after_run: Callable[[], Awaitable[None] | None] | None = None,
        after_decisions: Callable[[], Awaitable[None] | None] | None = None,
        after_citations: Callable[[], Awaitable[None] | None] | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.settings = settings
        self.trace = trace_service or TraceService(session)
        self.after_run = after_run
        self.after_decisions = after_decisions
        self.after_citations = after_citations

    async def retrieve(self, command: StartGraphRetrieval) -> RetrievalRecord:
        normalized_query = " ".join(command.query.split())
        selected = tuple(dict.fromkeys(command.selected_object_ids))
        seeds = tuple(dict.fromkeys(command.seed_object_ids))
        self._validate(command, normalized_query, selected, seeds)
        graph_revision = (
            await self.session.scalar(
                select(WorkspaceGraphState.revision).where(
                    WorkspaceGraphState.workspace_id == command.workspace_id
                )
            )
            or 0
        )
        request_values = {
            "algorithmVersion": RETRIEVAL_ALGORITHM_VERSION,
            "schemaVersion": RETRIEVAL_SCHEMA_VERSION,
            "userId": str(command.user_id),
            "workspaceId": str(command.workspace_id),
            "canvasId": str(command.canvas_id),
            "query": normalized_query,
            "selectedObjectIds": [str(value) for value in selected],
            "seedObjectIds": [str(value) for value in seeds],
            "graphRevision": graph_revision,
            "maxDepth": command.max_depth,
            "topK": command.top_k,
            "minRelevance": command.min_relevance,
        }
        request_digest = _digest(request_values)
        existing = await self.session.scalar(
            select(GraphRetrievalRun).where(
                GraphRetrievalRun.user_id == command.user_id,
                GraphRetrievalRun.workspace_id == command.workspace_id,
                GraphRetrievalRun.canvas_id == command.canvas_id,
                GraphRetrievalRun.idempotency_key == command.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise GraphRetrievalConflictError()
            return await self._record(existing, duplicate=True)
        retrieval_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mobius-retrieval:{request_digest}:{command.idempotency_key}",
        )
        try:
            context = await self.trace.start_trace(
                StartTraceInput(
                    trace_id=uuid.uuid5(retrieval_id, "trace"),
                    event_type="graph_retrieval.started",
                    actor_id=str(command.user_id),
                    actor_type="user",
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    object_id=retrieval_id,
                    object_type="graph_retrieval",
                    operation="graph_retrieval.execute",
                    metadata={
                        "algorithmVersion": RETRIEVAL_ALGORITHM_VERSION,
                        "graphRevision": graph_revision,
                        "selectedCount": len(selected),
                        "seedCount": len(seeds),
                        "maxDepth": command.max_depth,
                        "topK": command.top_k,
                    },
                )
            )
        except TracePersistenceError as exc:
            raise GraphRetrievalStorageError() from exc
        try:
            async with self.session.begin_nested():
                entities = await self._resolve_scope(command, selected)
                distances, paths, edge_decisions, bounded, conflict = await self._traverse(
                    command,
                    entities,
                    selected,
                    seeds,
                )
                passages, passage_decisions = await self._passages(
                    command,
                    entities,
                    distances,
                    paths,
                )
                passages = sorted(
                    passages,
                    key=lambda item: (
                        -item.score,
                        item.distance,
                        item.object_id.hex,
                        item.passage_identity,
                    ),
                )[: command.top_k]
                total_characters = 0
                included: list[_Passage] = []
                for passage in passages:
                    if total_characters + len(passage.excerpt) > MAX_RESPONSE_CHARACTERS:
                        bounded = True
                        break
                    included.append(passage)
                    total_characters += len(passage.excerpt)
                outcome: RetrievalOutcome
                if bounded:
                    outcome = "bounded_result"
                elif not included:
                    outcome = "insufficient_evidence"
                elif conflict:
                    outcome = "conflicting_evidence"
                else:
                    outcome = "supported"
                run = GraphRetrievalRun(
                    retrieval_id=retrieval_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    canvas_id=command.canvas_id,
                    idempotency_key=command.idempotency_key,
                    request_digest=request_digest,
                    query_text=normalized_query,
                    query_digest=_digest({"query": normalized_query}),
                    selected_object_ids=[str(value) for value in selected],
                    seed_object_ids=[str(value) for value in seeds],
                    graph_revision=graph_revision,
                    algorithm_version=RETRIEVAL_ALGORITHM_VERSION,
                    schema_version=RETRIEVAL_SCHEMA_VERSION,
                    mode="selected_graph",
                    outcome=outcome,
                    bounded=bounded,
                    citation_count=len(included),
                    trace_id=context.trace_id,
                    audit_event_id=None,
                )
                self.session.add(run)
                await self.session.flush()
                await _run_hook(self.after_run)
                decisions = edge_decisions + passage_decisions
                for decision in decisions:
                    decision.retrieval_id = retrieval_id
                    self.session.add(decision)
                await self.session.flush()
                await _run_hook(self.after_decisions)
                citations = [
                    self._citation(command, retrieval_id, context.trace_id, graph_revision, item, i)
                    for i, item in enumerate(included, 1)
                ]
                for citation in citations:
                    self.session.add(citation)
                await self.session.flush()
                await _run_hook(self.after_citations)
                await self.trace.complete_trace(
                    CompleteTraceInput(
                        trace_id=context.trace_id,
                        event_type="graph_retrieval.succeeded",
                        actor_id=str(command.user_id),
                        actor_type="user",
                        user_id=command.user_id,
                        workspace_id=command.workspace_id,
                        object_id=retrieval_id,
                        object_type="graph_retrieval",
                        operation="graph_retrieval.execute",
                        metadata={
                            "outcome": outcome,
                            "graphRevision": graph_revision,
                            "decisionCount": len(decisions),
                            "citationCount": len(citations),
                            "bounded": bounded,
                            "conflict": conflict,
                        },
                    )
                )
        except GraphRetrievalError as exc:
            await self._fail(context, command, retrieval_id, exc)
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            error = GraphRetrievalStorageError()
            await self._fail(context, command, retrieval_id, error)
            raise error from exc
        return RetrievalRecord(run, tuple(decisions), tuple(citations))

    async def get_owned(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        retrieval_id: uuid.UUID,
    ) -> RetrievalRecord:
        run = await self.session.scalar(
            select(GraphRetrievalRun).where(
                GraphRetrievalRun.retrieval_id == retrieval_id,
                GraphRetrievalRun.user_id == user_id,
                GraphRetrievalRun.workspace_id == workspace_id,
                GraphRetrievalRun.canvas_id == canvas_id,
            )
        )
        if run is None:
            raise GraphRetrievalNotFoundError()
        return await self._record(run)

    async def render_apa(
        self,
        record: RetrievalRecord,
        *,
        user_id: uuid.UUID,
    ) -> tuple[ApaCitation, ...]:
        try:
            rendered = tuple(_apa(citation) for citation in record.citations)
        except GraphRetrievalValidationError:
            await DomainEventService(self.session).record(
                CreateDomainEvent(
                    event_type="citation.rendering.failed",
                    user_id=user_id,
                    workspace_id=record.run.workspace_id,
                    canvas_id=record.run.canvas_id,
                    subject_id=record.run.retrieval_id,
                    actor_user_id=user_id,
                    source_identity=f"{record.run.retrieval_id}:apa7:failed",
                    trace_id=record.run.trace_id,
                    payload={
                        "retrievalId": str(record.run.retrieval_id),
                        "style": "apa7",
                        "status": "failed",
                        "failureCode": "unsupported_source_type",
                    },
                    origin_type="authenticated_user",
                )
            )
            raise
        await DomainEventService(self.session).record(
            CreateDomainEvent(
                event_type="citation.rendering.completed",
                user_id=user_id,
                workspace_id=record.run.workspace_id,
                canvas_id=record.run.canvas_id,
                subject_id=record.run.retrieval_id,
                actor_user_id=user_id,
                source_identity=f"{record.run.retrieval_id}:apa7",
                trace_id=record.run.trace_id,
                payload={
                    "retrievalId": str(record.run.retrieval_id),
                    "style": "apa7",
                    "status": "completed",
                },
                origin_type="authenticated_user",
            )
        )
        return rendered

    async def _record(self, run: GraphRetrievalRun, *, duplicate: bool = False) -> RetrievalRecord:
        decisions = tuple(
            (
                await self.session.scalars(
                    select(GraphRetrievalDecision)
                    .where(GraphRetrievalDecision.retrieval_id == run.retrieval_id)
                    .order_by(
                        GraphRetrievalDecision.included.desc(),
                        GraphRetrievalDecision.rank,
                        GraphRetrievalDecision.decision_id,
                    )
                )
            ).all()
        )
        citations = tuple(
            (
                await self.session.scalars(
                    select(GraphRetrievalCitation)
                    .where(GraphRetrievalCitation.retrieval_id == run.retrieval_id)
                    .order_by(GraphRetrievalCitation.ordinal)
                )
            ).all()
        )
        if len(citations) != run.citation_count:
            raise GraphRetrievalStorageError()
        return RetrievalRecord(run, decisions, citations, duplicate)

    async def _resolve_scope(
        self,
        command: StartGraphRetrieval,
        selected: tuple[uuid.UUID, ...],
    ) -> dict[uuid.UUID, _Entity]:
        workspace = await self.session.scalar(
            select(Workspace.id).where(
                Workspace.id == command.workspace_id,
                Workspace.owner_id == command.user_id,
                Workspace.lifecycle_state != "deleted",
            )
        )
        canvas = await self.session.scalar(
            select(Canvas.id).where(
                Canvas.id == command.canvas_id,
                Canvas.workspace_id == command.workspace_id,
            )
        )
        if workspace is None or canvas is None:
            raise GraphRetrievalNotFoundError()
        rows = (
            await self.session.execute(
                select(
                    CanonicalObject,
                    CanonicalGraphEntity,
                    CanonicalDocument,
                    CanonicalNote,
                )
                .join(
                    CanonicalGraphEntity,
                    CanonicalGraphEntity.object_id == CanonicalObject.id,
                )
                .join(
                    CanonicalCanvasObjectBinding,
                    CanonicalCanvasObjectBinding.object_id == CanonicalObject.id,
                )
                .outerjoin(CanonicalDocument, CanonicalDocument.object_id == CanonicalObject.id)
                .outerjoin(CanonicalNote, CanonicalNote.object_id == CanonicalObject.id)
                .where(
                    CanonicalObject.id.in_(selected),
                    CanonicalObject.workspace_id == command.workspace_id,
                    CanonicalObject.lifecycle_state.in_(("created", "active")),
                    CanonicalGraphEntity.user_id == command.user_id,
                    CanonicalCanvasObjectBinding.canvas_id == command.canvas_id,
                )
            )
        ).all()
        entities: dict[uuid.UUID, _Entity] = {}
        for obj, graph, document, note in rows:
            if graph.entity_kind == "document" and document is not None:
                entities[obj.id] = _Entity(
                    obj,
                    document.display_name,
                    None,
                    document.source_type,
                    document.legacy_document_id,
                )
            elif graph.entity_kind == "note" and note is not None:
                entities[obj.id] = _Entity(obj, note.title, note.content, "internal_note", None)
        if set(entities) != set(selected):
            raise GraphRetrievalNotFoundError()
        return entities

    async def _traverse(
        self,
        command: StartGraphRetrieval,
        entities: dict[uuid.UUID, _Entity],
        selected: tuple[uuid.UUID, ...],
        seeds: tuple[uuid.UUID, ...],
    ) -> tuple[
        dict[uuid.UUID, int],
        dict[uuid.UUID, tuple[uuid.UUID, ...]],
        list[GraphRetrievalDecision],
        bool,
        bool,
    ]:
        rows = (
            await self.session.execute(
                select(
                    CanonicalGraphRelationship,
                    CanonicalRelationship.relationship_type,
                    CanonicalRelationshipHistory,
                )
                .join(
                    CanonicalRelationship,
                    CanonicalRelationship.object_id == CanonicalGraphRelationship.relationship_id,
                )
                .join(
                    CanonicalRelationshipHistory,
                    CanonicalRelationshipHistory.relationship_id
                    == CanonicalGraphRelationship.relationship_id,
                )
                .where(
                    CanonicalGraphRelationship.user_id == command.user_id,
                    CanonicalGraphRelationship.workspace_id == command.workspace_id,
                    CanonicalGraphRelationship.canvas_id == command.canvas_id,
                    or_(
                        CanonicalGraphRelationship.source_object_id.in_(selected),
                        CanonicalGraphRelationship.target_object_id.in_(selected),
                    ),
                )
                .order_by(
                    CanonicalRelationshipHistory.relationship_id,
                    CanonicalRelationshipHistory.graph_revision.desc(),
                )
                .limit(MAX_RELATIONSHIPS + 1)
            )
        ).all()
        bounded = len(rows) > MAX_RELATIONSHIPS
        latest: dict[uuid.UUID, tuple[CanonicalGraphRelationship, str, str]] = {}
        for graph, kind, history in rows[:MAX_RELATIONSHIPS]:
            latest.setdefault(graph.relationship_id, (graph, kind, history.state))
        adjacency: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str]]] = {}
        decisions: list[GraphRetrievalDecision] = []
        conflict = False
        for graph, kind, state in latest.values():
            if state != "active":
                decisions.append(
                    self._decision(
                        command,
                        graph.source_object_id,
                        graph.relationship_id,
                        False,
                        "superseded_relationship"
                        if state == "superseded"
                        else "inactive_relationship",
                        0,
                        None,
                        None,
                        (),
                    )
                )
                continue
            if kind not in RELATIONSHIP_DIRECTIONS:
                decisions.append(
                    self._decision(
                        command,
                        graph.source_object_id,
                        graph.relationship_id,
                        False,
                        "unsupported_relationship_kind",
                        0,
                        None,
                        None,
                        (),
                    )
                )
                continue
            if graph.source_object_id not in entities or graph.target_object_id not in entities:
                decisions.append(
                    self._decision(
                        command,
                        graph.source_object_id,
                        graph.relationship_id,
                        False,
                        "outside_selected_context",
                        0,
                        None,
                        None,
                        (),
                    )
                )
                continue
            adjacency.setdefault(graph.source_object_id, []).append(
                (graph.target_object_id, graph.relationship_id, kind)
            )
            if RELATIONSHIP_DIRECTIONS[kind] == "both":
                adjacency.setdefault(graph.target_object_id, []).append(
                    (graph.source_object_id, graph.relationship_id, kind)
                )
        for edges in adjacency.values():
            edges.sort(key=lambda item: (item[2], item[0].hex, item[1].hex))
        distances = {seed: 0 for seed in seeds}
        paths: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {seed: () for seed in seeds}
        queue = deque(seeds)
        while queue:
            current = queue.popleft()
            distance = distances[current]
            if distance >= command.max_depth:
                if adjacency.get(current):
                    bounded = True
                continue
            for target, relationship_id, kind in adjacency.get(current, []):
                path = paths[current] + (relationship_id,)
                if target in distances:
                    continue
                if len(distances) >= MAX_ENTITIES:
                    bounded = True
                    break
                distances[target] = distance + 1
                paths[target] = path
                queue.append(target)
                if kind == "contradicts":
                    conflict = True
                decisions.append(
                    self._decision(
                        command,
                        target,
                        relationship_id,
                        True,
                        _relationship_reason(kind),
                        distance + 1,
                        None,
                        None,
                        path,
                    )
                )
        for seed in seeds:
            decisions.append(
                self._decision(
                    command,
                    seed,
                    None,
                    True,
                    "selected_seed",
                    0,
                    None,
                    None,
                    (),
                )
            )
        return distances, paths, decisions, bounded, conflict

    async def _passages(
        self,
        command: StartGraphRetrieval,
        entities: dict[uuid.UUID, _Entity],
        distances: dict[uuid.UUID, int],
        paths: dict[uuid.UUID, tuple[uuid.UUID, ...]],
    ) -> tuple[list[_Passage], list[GraphRetrievalDecision]]:
        passages: list[_Passage] = []
        decisions: list[GraphRetrievalDecision] = []
        query_terms = _terms(command.query)
        document_map = {
            entity.legacy_document_id: object_id
            for object_id, entity in entities.items()
            if object_id in distances and entity.legacy_document_id is not None
        }
        if document_map:
            retrieved = await search_documents(
                self.session,
                document_ids=tuple(document_map),
                query=command.query,
                provider=self.embedding_provider,
                top_k=min(MAX_PASSAGES, MAX_CANDIDATES),
                threshold=command.min_relevance,
                settings=self.settings,
            )
            versions = {
                (row.document_id, row.version): row
                for row in (
                    await self.session.scalars(
                        select(DocumentVersion).where(
                            DocumentVersion.document_id.in_(tuple(document_map))
                        )
                    )
                ).all()
            }
            for item in retrieved[:MAX_CANDIDATES]:
                object_id = document_map[item.document_id]
                version = versions.get((item.document_id, item.document_version))
                if version is None or version.deleted_at is not None:
                    decisions.append(
                        self._decision(
                            command,
                            object_id,
                            None,
                            False,
                            "missing_immutable_version",
                            distances[object_id],
                            item.rank,
                            item.score,
                            paths[object_id],
                        )
                    )
                    continue
                included = item.included_in_context
                decisions.append(
                    self._decision(
                        command,
                        object_id,
                        None,
                        included,
                        "exact_source_passage_match" if included else "insufficient_relevance",
                        distances[object_id],
                        item.rank,
                        item.score,
                        paths[object_id],
                    )
                )
                if included:
                    passages.append(
                        _document_passage(
                            entities[object_id],
                            object_id,
                            item,
                            version.content_sha256,
                            distances[object_id],
                            paths[object_id],
                        )
                    )
        for object_id, entity in entities.items():
            if object_id not in distances or entity.text is None:
                continue
            score = _lexical_score(query_terms, _terms(entity.text))
            included = bool(entity.text.strip()) and score >= command.min_relevance
            decisions.append(
                self._decision(
                    command,
                    object_id,
                    None,
                    included,
                    "approved_deterministic_fallback" if included else "insufficient_relevance",
                    distances[object_id],
                    None,
                    score,
                    paths[object_id],
                )
            )
            if included:
                passages.append(
                    _Passage(
                        object_id=object_id,
                        title=entity.title,
                        source_type=entity.source_type,
                        canonical_version=entity.object.version,
                        source_version=entity.object.version,
                        source_sha256=_sha(entity.text),
                        passage_identity=f"note:{object_id}:v{entity.object.version}",
                        excerpt=entity.text,
                        locator={"charStart": 0, "charEnd": len(entity.text)},
                        score=score - distances[object_id] * 0.01,
                        distance=distances[object_id],
                        path=paths[object_id],
                    )
                )
        return passages[:MAX_CANDIDATES], decisions

    def _citation(
        self,
        command: StartGraphRetrieval,
        retrieval_id: uuid.UUID,
        trace_id: uuid.UUID,
        graph_revision: int,
        passage: _Passage,
        ordinal: int,
    ) -> GraphRetrievalCitation:
        citation_id = uuid.uuid5(retrieval_id, passage.passage_identity)
        return GraphRetrievalCitation(
            citation_id=citation_id,
            retrieval_id=retrieval_id,
            user_id=command.user_id,
            workspace_id=command.workspace_id,
            canonical_object_id=passage.object_id,
            canonical_version=passage.canonical_version,
            source_version=passage.source_version,
            source_sha256=passage.source_sha256,
            source_title=passage.title,
            source_type=passage.source_type,
            passage_identity=passage.passage_identity,
            excerpt=passage.excerpt,
            excerpt_sha256=_sha(passage.excerpt),
            locator=passage.locator,
            relationship_path=[str(value) for value in passage.path],
            graph_revision=graph_revision,
            ordinal=ordinal,
            citation_schema_version=CITATION_SCHEMA_VERSION,
            trace_id=trace_id,
            audit_event_id=None,
        )

    def _decision(
        self,
        command: StartGraphRetrieval,
        object_id: uuid.UUID,
        relationship_id: uuid.UUID | None,
        included: bool,
        reason: str,
        distance: int,
        rank: int | None,
        score: float | None,
        path: tuple[uuid.UUID, ...],
    ) -> GraphRetrievalDecision:
        if reason not in INCLUSION_REASONS | EXCLUSION_REASONS:
            raise GraphRetrievalValidationError("Unknown retrieval reason.")
        identity = ":".join(
            (
                command.idempotency_key,
                str(object_id),
                str(relationship_id),
                reason,
                str(rank),
            )
        )
        return GraphRetrievalDecision(
            decision_id=uuid.uuid5(uuid.NAMESPACE_URL, identity),
            retrieval_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"mobius-retrieval:{_digest(self._request_values_for_identity(command))}",
            ),
            user_id=command.user_id,
            workspace_id=command.workspace_id,
            object_id=object_id,
            relationship_id=relationship_id,
            included=included,
            reason_code=reason,
            distance=distance,
            rank=rank,
            score=score,
            relationship_path=[str(value) for value in path],
            detail={},
        )

    @staticmethod
    def _request_values_for_identity(command: StartGraphRetrieval) -> dict[str, object]:
        # Decision retrieval_id is replaced by the authoritative caller before flush.
        return {"idempotencyKey": command.idempotency_key}

    @staticmethod
    def _validate(
        command: StartGraphRetrieval,
        query: str,
        selected: tuple[uuid.UUID, ...],
        seeds: tuple[uuid.UUID, ...],
    ) -> None:
        if not query or len(query) > MAX_QUERY_CHARACTERS:
            raise GraphRetrievalValidationError("Query is outside its bound.")
        if not 1 <= len(selected) <= MAX_SELECTED or not 1 <= len(seeds) <= MAX_SEEDS:
            raise GraphRetrievalValidationError("Selected context is outside its bound.")
        if not set(seeds) <= set(selected):
            raise GraphRetrievalValidationError("Seeds must be within selected context.")
        if not 0 <= command.max_depth <= MAX_DEPTH:
            raise GraphRetrievalValidationError("Traversal depth is outside its bound.")
        if not 1 <= command.top_k <= MAX_PASSAGES:
            raise GraphRetrievalValidationError("Passage limit is outside its bound.")
        if not -1 <= command.min_relevance <= 1:
            raise GraphRetrievalValidationError("Relevance threshold is invalid.")
        if not command.idempotency_key.strip() or len(command.idempotency_key) > 128:
            raise GraphRetrievalValidationError("Idempotency identity is invalid.")

    async def _fail(
        self,
        context: TraceContext,
        command: StartGraphRetrieval,
        retrieval_id: uuid.UUID,
        error: GraphRetrievalError,
    ) -> None:
        try:
            await self.trace.fail_trace(
                FailTraceInput(
                    trace_id=context.trace_id,
                    event_type="graph_retrieval.failed",
                    actor_id=str(command.user_id),
                    actor_type="user",
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    object_id=retrieval_id,
                    object_type="graph_retrieval",
                    operation="graph_retrieval.execute",
                    error=TraceErrorInfo(code=error.code, message=error.safe_message),
                )
            )
        except TracePersistenceError as exc:
            raise GraphRetrievalStorageError() from exc


class TraceEvidenceBundleService:
    """Synchronous deterministic bundle builder with no autonomous worker."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate(
        self,
        record: RetrievalRecord,
        *,
        user_id: uuid.UUID,
    ) -> TraceEvidenceBundle:
        existing = await self.session.scalar(
            select(TraceEvidenceBundle).where(
                TraceEvidenceBundle.retrieval_id == record.run.retrieval_id,
                TraceEvidenceBundle.user_id == user_id,
            )
        )
        if existing is not None:
            return existing
        bundle_id = uuid.uuid5(record.run.retrieval_id, BUNDLE_SCHEMA_VERSION)
        apa = tuple(_apa(citation) for citation in record.citations)
        artifact, manifest = _bundle_bytes(record, bundle_id, apa)
        if len(artifact) > MAX_BUNDLE_BYTES:
            raise GraphRetrievalValidationError("Evidence bundle exceeds its size bound.")
        bundle = TraceEvidenceBundle(
            bundle_id=bundle_id,
            retrieval_id=record.run.retrieval_id,
            user_id=user_id,
            workspace_id=record.run.workspace_id,
            canvas_id=record.run.canvas_id,
            schema_version=BUNDLE_SCHEMA_VERSION,
            state="completed",
            manifest=manifest,
            artifact_bytes=artifact,
            artifact_sha256=_sha_bytes(artifact),
            byte_size=len(artifact),
            trace_id=record.run.trace_id,
            audit_event_id=None,
        )
        async with self.session.begin_nested():
            self.session.add(bundle)
            await self.session.flush()
            events = DomainEventService(self.session)
            for event_type, state in (
                ("evidence.bundle.requested", "requested"),
                ("evidence.bundle.generation_started", "generation_started"),
                ("evidence.bundle.completed", "completed"),
            ):
                await events.record(
                    CreateDomainEvent(
                        event_type=event_type,
                        user_id=user_id,
                        workspace_id=record.run.workspace_id,
                        canvas_id=record.run.canvas_id,
                        subject_id=bundle_id,
                        related_id=record.run.retrieval_id,
                        actor_user_id=user_id,
                        source_identity=f"{bundle_id}:{state}",
                        trace_id=record.run.trace_id,
                        payload={
                            "retrievalId": str(record.run.retrieval_id),
                            "bundleState": state,
                            **(
                                {"artifactSha256": cast(str, bundle.artifact_sha256)}
                                if state == "completed"
                                else {}
                            ),
                        },
                        origin_type="authenticated_user",
                    )
                )
        return bundle

    async def get_owned(
        self,
        *,
        bundle_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
    ) -> TraceEvidenceBundle:
        bundle = await self.session.scalar(
            select(TraceEvidenceBundle).where(
                TraceEvidenceBundle.bundle_id == bundle_id,
                TraceEvidenceBundle.user_id == user_id,
                TraceEvidenceBundle.workspace_id == workspace_id,
                TraceEvidenceBundle.canvas_id == canvas_id,
            )
        )
        if bundle is None:
            raise GraphRetrievalNotFoundError()
        if (
            bundle.state != "completed"
            or bundle.artifact_bytes is None
            or bundle.artifact_sha256 != _sha_bytes(bundle.artifact_bytes)
        ):
            raise GraphRetrievalStorageError()
        return bundle


def _document_passage(
    entity: _Entity,
    object_id: uuid.UUID,
    item: RetrievedChunk,
    source_hash: str,
    distance: int,
    path: tuple[uuid.UUID, ...],
) -> _Passage:
    return _Passage(
        object_id=object_id,
        title=entity.title,
        source_type=entity.source_type,
        canonical_version=entity.object.version,
        source_version=item.document_version,
        source_sha256=source_hash,
        passage_identity=f"chunk:{item.chunk_id}:v{item.document_version}",
        excerpt=item.content,
        locator={
            "chunkId": str(item.chunk_id),
            "chunkIndex": item.chunk_index,
            "pageNumber": item.page_number,
            "heading": item.heading,
            "charStart": item.char_start,
            "charEnd": item.char_end,
        },
        score=item.score - distance * 0.01,
        distance=distance,
        path=path,
    )


def _relationship_reason(kind: str) -> str:
    return {
        "references": "reference_relationship",
        "cites": "direct_citation",
        "supports": "supporting_relationship",
        "derived_from": "derivation_relationship",
    }.get(kind, "graph_related_candidate")


def _terms(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[\w'-]+", text.casefold()))


def _lexical_score(query: frozenset[str], content: frozenset[str]) -> float:
    if not query:
        return 0.0
    return len(query & content) / len(query)


def _apa(citation: GraphRetrievalCitation) -> ApaCitation:
    title = _escape(citation.source_title)
    if citation.source_type == "internal_note":
        label = "Internal note"
    elif citation.source_type.casefold() in {"pdf", "docx", "txt", "md", "upload"}:
        label = f"Uploaded {citation.source_type.upper()} document"
    else:
        raise GraphRetrievalValidationError("APA rendering does not support this source type.")
    page = citation.locator.get("pageNumber")
    locator = f", p. {page}" if isinstance(page, int) else ""
    return ApaCitation(
        citation_id=citation.citation_id,
        in_text=f"({title}, n.d.{locator})",
        reference=f"{title}. (n.d.). [{label}].",
    )


def _bundle_bytes(
    record: RetrievalRecord,
    bundle_id: uuid.UUID,
    apa: tuple[ApaCitation, ...],
) -> tuple[bytes, dict[str, object]]:
    citations_json = [
        {
            "citationId": str(item.citation_id),
            "canonicalObjectId": str(item.canonical_object_id),
            "canonicalVersion": item.canonical_version,
            "sourceVersion": item.source_version,
            "sourceSha256": item.source_sha256,
            "excerpt": item.excerpt,
            "excerptSha256": item.excerpt_sha256,
            "locator": item.locator,
            "relationshipPath": item.relationship_path,
            "traceId": str(item.trace_id),
            "apa": {
                "inText": apa[index].in_text,
                "reference": apa[index].reference,
            },
        }
        for index, item in enumerate(record.citations)
    ]
    members: dict[str, bytes] = {
        "README.md": (
            b"# Trace Evidence Bundle\n\n"
            b"This deterministic bundle contains only exact authorized excerpts. "
            b"Complete private sources were omitted because no export authority "
            b"contract exists in Milestone 5.3.\n"
        ),
        "trace-report.md": (
            f"# Retrieval Trace\n\nQuestion: {_escape(record.run.query_text)}\n\n"
            f"Outcome: `{record.run.outcome}`\n\n"
            f"Graph revision: `{record.run.graph_revision}`\n\n"
            f"Trace: `{record.run.trace_id}`\n"
        ).encode(),
        "references.md": (
            "# References\n\n"
            + "\n\n".join(item.reference for item in sorted(apa, key=lambda value: value.reference))
            + "\n"
        ).encode(),
        "citations.json": _json_bytes(citations_json),
    }
    for index, citation in enumerate(record.citations, 1):
        members[f"excerpts/source-{index:03d}-excerpt.txt"] = citation.excerpt.replace(
            "\r\n", "\n"
        ).encode("utf-8")
    if len(members) + 2 > MAX_BUNDLE_FILES:
        raise GraphRetrievalValidationError("Evidence bundle exceeds its file bound.")
    hashes = {name: _sha_bytes(content) for name, content in sorted(members.items())}
    manifest: dict[str, object] = {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "bundleId": str(bundle_id),
        "retrievalId": str(record.run.retrieval_id),
        "workspaceId": str(record.run.workspace_id),
        "canvasId": str(record.run.canvas_id),
        "graphRevision": record.run.graph_revision,
        "traceId": str(record.run.trace_id),
        "outcome": record.run.outcome,
        "files": [
            {"path": name, "sha256": digest, "byteSize": len(members[name])}
            for name, digest in sorted(hashes.items())
        ],
        "sourceExport": {
            "included": False,
            "reasonCode": "export_not_authorized",
        },
    }
    members["manifest.json"] = _json_bytes(manifest)
    checksum_lines = [
        f"{_sha_bytes(content)}  {name}\n" for name, content in sorted(members.items())
    ]
    members["integrity/sha256sums.txt"] = "".join(checksum_lines).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(members.items()):
            if name.startswith("/") or ".." in name.split("\\") or ".." in name.split("/"):
                raise GraphRetrievalValidationError("Unsafe evidence filename.")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, content)
    return output.getvalue(), manifest


def _escape(value: str) -> str:
    return re.sub(r"([\\`*_[\]<>])", r"\\\1", value.replace("\r", " ").replace("\n", " "))


def _digest(value: object) -> str:
    return _sha_bytes(_json_bytes(value))


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        .replace("\r\n", "\n")
        .encode("utf-8")
    )


def _sha(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


async def _run_hook(hook: Callable[[], Awaitable[None] | None] | None) -> None:
    if hook is None:
        return
    result = hook()
    if result is not None:
        await result


__all__ = [
    "APA_RENDERER_VERSION",
    "BUNDLE_SCHEMA_VERSION",
    "CITATION_SCHEMA_VERSION",
    "EXCLUSION_REASONS",
    "INCLUSION_REASONS",
    "RELATIONSHIP_DIRECTIONS",
    "RETRIEVAL_ALGORITHM_VERSION",
    "RETRIEVAL_OUTCOMES",
    "GraphAwareRetrievalService",
    "GraphRetrievalConflictError",
    "GraphRetrievalError",
    "GraphRetrievalNotFoundError",
    "GraphRetrievalStorageError",
    "GraphRetrievalValidationError",
    "RetrievalRecord",
    "StartGraphRetrieval",
    "TraceEvidenceBundleService",
]
