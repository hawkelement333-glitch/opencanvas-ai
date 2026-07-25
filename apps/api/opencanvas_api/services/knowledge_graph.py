from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import Select, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    CanonicalCanvasObjectBinding,
    CanonicalGraphEntity,
    CanonicalGraphRelationship,
    CanonicalObject,
    CanonicalRelationship,
    CanonicalRelationshipHistory,
    CanonicalRelationshipProvenance,
    Canvas,
    Workspace,
    WorkspaceGraphState,
)
from opencanvas_api.services.canonical.lifecycle import (
    CanonicalConflictError,
    CanonicalDomainError,
    CanonicalNotFoundError,
    CanonicalStorageError,
    CanonicalValidationError,
)
from opencanvas_api.services.domain_events import (
    CreateDomainEvent,
    DomainEventError,
    DomainEventService,
)
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    FailTraceInput,
    StartTraceInput,
    TraceContext,
    TraceErrorInfo,
    TracePersistenceError,
    TraceService,
)

GraphEntityKind = Literal["document", "note", "execution"]
GraphRelationshipType = Literal[
    "references",
    "derived_from",
    "related_to",
    "cites",
    "supports",
    "contradicts",
    "produced_by",
    "affected_by",
]
GraphHistoryState = Literal["active", "inactive", "superseded", "rejected"]

GRAPH_ENTITY_KINDS = frozenset({"document", "note", "execution"})
GRAPH_RELATIONSHIP_TYPES = frozenset(
    {
        "references",
        "derived_from",
        "related_to",
        "cites",
        "supports",
        "contradicts",
        "produced_by",
        "affected_by",
    }
)
GRAPH_SCHEMA_VERSION = "knowledge-graph-v1"
MAX_CYCLE_CHECK_EDGES = 500

_ALL_KINDS = GRAPH_ENTITY_KINDS
_RELATIONSHIP_COMPATIBILITY: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "references": (_ALL_KINDS, _ALL_KINDS),
    "derived_from": (
        frozenset({"note", "execution"}),
        frozenset({"document", "note", "execution"}),
    ),
    "related_to": (_ALL_KINDS, _ALL_KINDS),
    "cites": (frozenset({"note", "execution"}), frozenset({"document"})),
    "supports": (
        frozenset({"document", "note"}),
        frozenset({"note", "execution"}),
    ),
    "contradicts": (
        frozenset({"document", "note"}),
        frozenset({"document", "note"}),
    ),
    "produced_by": (frozenset({"document", "note"}), frozenset({"execution"})),
    "affected_by": (frozenset({"document", "note"}), frozenset({"execution"})),
}
_ACYCLIC_TYPES = frozenset({"derived_from"})


@dataclass(frozen=True, slots=True)
class GraphEntityReference:
    kind: GraphEntityKind
    object_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class CreateGraphRelationship:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    relationship_type: GraphRelationshipType
    source: GraphEntityReference
    target: GraphEntityReference
    idempotency_key: str
    parent_trace_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class DeactivateGraphRelationship:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID
    relationship_id: uuid.UUID
    expected_version: int
    idempotency_key: str
    target_state: Literal["inactive", "superseded", "rejected"]
    reason_code: str
    parent_trace_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class GraphRelationshipRecord:
    graph: CanonicalGraphRelationship
    relationship: CanonicalRelationship
    object: CanonicalObject
    provenance: CanonicalRelationshipProvenance
    current_history: CanonicalRelationshipHistory
    source: CanonicalGraphEntity
    target: CanonicalGraphEntity
    replayed: bool = False


class KnowledgeGraphService:
    """Scoped canonical graph commands and bounded history reads."""

    def __init__(
        self,
        session: AsyncSession,
        trace_service: TraceService | None = None,
        event_service: DomainEventService | None = None,
    ) -> None:
        self._session = session
        self._trace = trace_service or TraceService(session)
        self._events = event_service or DomainEventService(session)

    async def create_relationship(
        self, command: CreateGraphRelationship
    ) -> GraphRelationshipRecord:
        relationship_id = uuid.uuid4()
        request_digest = _digest(
            {
                "schemaVersion": GRAPH_SCHEMA_VERSION,
                "operation": "create",
                "userId": str(command.user_id),
                "workspaceId": str(command.workspace_id),
                "canvasId": str(command.canvas_id),
                "relationshipType": command.relationship_type,
                "source": {
                    "kind": command.source.kind,
                    "objectId": str(command.source.object_id),
                },
                "target": {
                    "kind": command.target.kind,
                    "objectId": str(command.target.object_id),
                },
            }
        )

        async def mutation(context: TraceContext) -> GraphRelationshipRecord:
            replay = await self._idempotent_create(
                command.user_id,
                command.workspace_id,
                command.canvas_id,
                command.idempotency_key,
                request_digest,
            )
            if replay is not None:
                return _with_replayed(replay)
            await self._require_scope(
                command.user_id,
                command.workspace_id,
                command.canvas_id,
            )
            source = await self._resolve_entity(
                command.user_id,
                command.workspace_id,
                command.canvas_id,
                command.source,
                context.trace_id,
            )
            target = await self._resolve_entity(
                command.user_id,
                command.workspace_id,
                command.canvas_id,
                command.target,
                context.trace_id,
            )
            self._validate_relationship(
                command.relationship_type,
                source,
                target,
            )
            await self._reject_existing_identity(
                command.workspace_id,
                command.relationship_type,
                source.object_id,
                target.object_id,
            )
            if command.relationship_type in _ACYCLIC_TYPES:
                await self._reject_cycle(
                    command.user_id,
                    command.workspace_id,
                    command.canvas_id,
                    command.relationship_type,
                    source.object_id,
                    target.object_id,
                )
            graph_revision = await self._advance_graph_revision(command.workspace_id)
            canonical_digest = _digest(
                {
                    "schemaVersion": GRAPH_SCHEMA_VERSION,
                    "relationshipId": str(relationship_id),
                    "userId": str(command.user_id),
                    "workspaceId": str(command.workspace_id),
                    "canvasId": str(command.canvas_id),
                    "relationshipType": command.relationship_type,
                    "sourceObjectId": str(source.object_id),
                    "targetObjectId": str(target.object_id),
                    "originType": "user_created",
                }
            )
            provenance_digest = _digest(
                {
                    "schemaVersion": GRAPH_SCHEMA_VERSION,
                    "relationshipDigest": canonical_digest,
                    "originType": "user_created",
                    "actorUserId": str(command.user_id),
                    "traceId": str(context.trace_id),
                }
            )
            canonical_object = CanonicalObject(
                id=relationship_id,
                workspace_id=command.workspace_id,
                object_type="relationship",
                version=1,
                lifecycle_state="active",
                metadata_payload={},
            )
            relationship = CanonicalRelationship(
                object_id=relationship_id,
                workspace_id=command.workspace_id,
                source_object_id=source.object_id,
                target_object_id=target.object_id,
                relationship_type=command.relationship_type,
                created_by=command.user_id,
                trace_id=context.trace_id,
            )
            graph = CanonicalGraphRelationship(
                relationship_id=relationship_id,
                workspace_id=command.workspace_id,
                user_id=command.user_id,
                canvas_id=command.canvas_id,
                source_object_id=source.object_id,
                target_object_id=target.object_id,
                schema_version=GRAPH_SCHEMA_VERSION,
                graph_revision=graph_revision,
                canonical_digest=canonical_digest,
                idempotency_key=command.idempotency_key,
                request_digest=request_digest,
            )
            provenance = CanonicalRelationshipProvenance(
                provenance_id=uuid.uuid4(),
                relationship_id=relationship_id,
                workspace_id=command.workspace_id,
                user_id=command.user_id,
                canvas_id=command.canvas_id,
                origin_type="user_created",
                actor_user_id=command.user_id,
                execution_id=None,
                source_reference_id=None,
                rule_id=None,
                rule_version=None,
                trace_id=context.trace_id,
                provenance_digest=provenance_digest,
            )
            history = CanonicalRelationshipHistory(
                history_id=uuid.uuid4(),
                relationship_id=relationship_id,
                workspace_id=command.workspace_id,
                user_id=command.user_id,
                canvas_id=command.canvas_id,
                state="active",
                reason_code=None,
                actor_user_id=command.user_id,
                trace_id=context.trace_id,
                graph_revision=graph_revision,
                previous_history_id=None,
                idempotency_key=command.idempotency_key,
                request_digest=request_digest,
            )
            self._session.add(canonical_object)
            await self._flush("Knowledge graph relationship identity persistence failed.")
            self._session.add(relationship)
            await self._flush("Knowledge graph relationship detail persistence failed.")
            self._session.add(graph)
            await self._flush("Knowledge graph relationship scope persistence failed.")
            self._session.add_all([provenance, history])
            await self._flush("Knowledge graph relationship persistence failed.")
            return GraphRelationshipRecord(
                graph=graph,
                relationship=relationship,
                object=canonical_object,
                provenance=provenance,
                current_history=history,
                source=source,
                target=target,
            )

        return await self._run_traced(
            user_id=command.user_id,
            workspace_id=command.workspace_id,
            canvas_id=command.canvas_id,
            object_id=relationship_id,
            operation="knowledge_graph.relationship.create",
            event_type="graph.relationship.created",
            source_identity=command.idempotency_key,
            parent_trace_id=command.parent_trace_id,
            mutation=mutation,
        )

    async def deactivate_relationship(
        self, command: DeactivateGraphRelationship
    ) -> GraphRelationshipRecord:
        request_digest = _digest(
            {
                "schemaVersion": GRAPH_SCHEMA_VERSION,
                "operation": "deactivate",
                "userId": str(command.user_id),
                "workspaceId": str(command.workspace_id),
                "canvasId": str(command.canvas_id),
                "relationshipId": str(command.relationship_id),
                "expectedVersion": command.expected_version,
                "targetState": command.target_state,
                "reasonCode": command.reason_code,
            }
        )

        async def mutation(context: TraceContext) -> GraphRelationshipRecord:
            replay_history = await self._session.scalar(
                select(CanonicalRelationshipHistory).where(
                    CanonicalRelationshipHistory.user_id == command.user_id,
                    CanonicalRelationshipHistory.workspace_id == command.workspace_id,
                    CanonicalRelationshipHistory.canvas_id == command.canvas_id,
                    CanonicalRelationshipHistory.idempotency_key == command.idempotency_key,
                )
            )
            if replay_history is not None:
                if replay_history.request_digest != request_digest:
                    raise CanonicalConflictError(
                        "The idempotency key was already used for a different graph mutation."
                    )
                record = await self.get_relationship(
                    command.user_id,
                    command.workspace_id,
                    command.canvas_id,
                    replay_history.relationship_id,
                )
                return _with_replayed(record)

            await self._require_scope(
                command.user_id,
                command.workspace_id,
                command.canvas_id,
            )
            record = await self.get_relationship(
                command.user_id,
                command.workspace_id,
                command.canvas_id,
                command.relationship_id,
            )
            if record.object.version != command.expected_version:
                raise CanonicalConflictError("Knowledge graph relationship version is stale.")
            if record.current_history.state != "active":
                raise CanonicalConflictError("Knowledge graph relationship is not active.")
            graph_revision = await self._advance_graph_revision(command.workspace_id)
            statement = (
                update(CanonicalObject)
                .where(
                    CanonicalObject.id == command.relationship_id,
                    CanonicalObject.workspace_id == command.workspace_id,
                    CanonicalObject.version == command.expected_version,
                    CanonicalObject.lifecycle_state == "active",
                )
                .values(
                    version=CanonicalObject.version + 1,
                    lifecycle_state="deleted",
                )
                .returning(CanonicalObject)
            )
            updated_object = await self._session.scalar(statement)
            if updated_object is None:
                raise CanonicalConflictError("Knowledge graph relationship version is stale.")
            history = CanonicalRelationshipHistory(
                history_id=uuid.uuid4(),
                relationship_id=command.relationship_id,
                workspace_id=command.workspace_id,
                user_id=command.user_id,
                canvas_id=command.canvas_id,
                state=command.target_state,
                reason_code=command.reason_code,
                actor_user_id=command.user_id,
                trace_id=context.trace_id,
                graph_revision=graph_revision,
                previous_history_id=record.current_history.history_id,
                idempotency_key=command.idempotency_key,
                request_digest=request_digest,
            )
            self._session.add(history)
            await self._flush("Knowledge graph relationship deactivation failed.")
            return GraphRelationshipRecord(
                graph=record.graph,
                relationship=record.relationship,
                object=updated_object,
                provenance=record.provenance,
                current_history=history,
                source=record.source,
                target=record.target,
            )

        return await self._run_traced(
            user_id=command.user_id,
            workspace_id=command.workspace_id,
            canvas_id=command.canvas_id,
            object_id=command.relationship_id,
            operation="knowledge_graph.relationship.deactivate",
            event_type=(
                "graph.relationship.superseded"
                if command.target_state == "superseded"
                else "graph.relationship.deactivated"
            ),
            source_identity=command.idempotency_key,
            parent_trace_id=command.parent_trace_id,
            mutation=mutation,
        )

    async def get_relationship(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        relationship_id: uuid.UUID,
    ) -> GraphRelationshipRecord:
        await self._require_scope(user_id, workspace_id, canvas_id)
        graph = await self._session.scalar(
            select(CanonicalGraphRelationship).where(
                CanonicalGraphRelationship.relationship_id == relationship_id,
                CanonicalGraphRelationship.user_id == user_id,
                CanonicalGraphRelationship.workspace_id == workspace_id,
                CanonicalGraphRelationship.canvas_id == canvas_id,
            )
        )
        if graph is None:
            raise CanonicalNotFoundError("Knowledge graph relationship not found.")
        relationship = await self._session.get(CanonicalRelationship, relationship_id)
        canonical_object = await self._session.get(CanonicalObject, relationship_id)
        provenance = await self._session.scalar(
            select(CanonicalRelationshipProvenance).where(
                CanonicalRelationshipProvenance.relationship_id == relationship_id
            )
        )
        history = await self._latest_history(relationship_id)
        source = await self._session.get(CanonicalGraphEntity, graph.source_object_id)
        target = await self._session.get(CanonicalGraphEntity, graph.target_object_id)
        if (
            relationship is None
            or canonical_object is None
            or provenance is None
            or history is None
            or source is None
            or target is None
        ):
            raise CanonicalStorageError("Knowledge graph relationship evidence is incomplete.")
        return GraphRelationshipRecord(
            graph=graph,
            relationship=relationship,
            object=canonical_object,
            provenance=provenance,
            current_history=history,
            source=source,
            target=target,
        )

    async def list_entity_relationships(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        entity_id: uuid.UUID,
        *,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GraphRelationshipRecord]:
        await self._require_scope(user_id, workspace_id, canvas_id)
        entity = await self._session.scalar(
            select(CanonicalGraphEntity)
            .join(
                CanonicalCanvasObjectBinding,
                CanonicalCanvasObjectBinding.object_id == CanonicalGraphEntity.object_id,
            )
            .where(
                CanonicalGraphEntity.object_id == entity_id,
                CanonicalGraphEntity.user_id == user_id,
                CanonicalGraphEntity.workspace_id == workspace_id,
                CanonicalCanvasObjectBinding.canvas_id == canvas_id,
            )
        )
        if entity is None:
            raise CanonicalNotFoundError("Knowledge graph entity not found.")
        statement: Select[tuple[CanonicalGraphRelationship]] = select(
            CanonicalGraphRelationship
        ).where(
            CanonicalGraphRelationship.user_id == user_id,
            CanonicalGraphRelationship.workspace_id == workspace_id,
            CanonicalGraphRelationship.canvas_id == canvas_id,
            or_(
                CanonicalGraphRelationship.source_object_id == entity_id,
                CanonicalGraphRelationship.target_object_id == entity_id,
            ),
        )
        statement = statement.order_by(
            CanonicalGraphRelationship.created_at,
            CanonicalGraphRelationship.relationship_id,
        )
        graphs = list((await self._session.scalars(statement.offset(offset).limit(limit))).all())
        records: list[GraphRelationshipRecord] = []
        for graph in graphs:
            record = await self.get_relationship(
                user_id,
                workspace_id,
                canvas_id,
                graph.relationship_id,
            )
            if include_inactive or record.current_history.state == "active":
                records.append(record)
        return records

    async def list_history(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        relationship_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CanonicalRelationshipHistory]:
        await self.get_relationship(user_id, workspace_id, canvas_id, relationship_id)
        return list(
            (
                await self._session.scalars(
                    select(CanonicalRelationshipHistory)
                    .where(CanonicalRelationshipHistory.relationship_id == relationship_id)
                    .order_by(
                        CanonicalRelationshipHistory.graph_revision,
                        CanonicalRelationshipHistory.history_id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )

    async def _resolve_entity(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        reference: GraphEntityReference,
        trace_id: uuid.UUID,
    ) -> CanonicalGraphEntity:
        if reference.kind not in GRAPH_ENTITY_KINDS:
            raise CanonicalValidationError("Knowledge graph entity kind is not supported.")
        canonical_object = await self._session.scalar(
            select(CanonicalObject).where(
                CanonicalObject.id == reference.object_id,
                CanonicalObject.workspace_id == workspace_id,
                CanonicalObject.object_type == reference.kind,
                CanonicalObject.lifecycle_state != "deleted",
            )
        )
        if canonical_object is None:
            raise CanonicalNotFoundError("Knowledge graph entity not found.")
        entity = await self._session.get(CanonicalGraphEntity, reference.object_id)
        if entity is None:
            entity = CanonicalGraphEntity(
                object_id=reference.object_id,
                workspace_id=workspace_id,
                user_id=user_id,
                entity_kind=reference.kind,
                created_by=user_id,
                trace_id=trace_id,
            )
            self._session.add(entity)
            await self._flush("Knowledge graph entity persistence failed.")
        elif (
            entity.workspace_id != workspace_id
            or entity.user_id != user_id
            or entity.entity_kind != reference.kind
        ):
            raise CanonicalNotFoundError("Knowledge graph entity not found.")
        binding = await self._session.scalar(
            select(CanonicalCanvasObjectBinding).where(
                CanonicalCanvasObjectBinding.object_id == reference.object_id,
                CanonicalCanvasObjectBinding.workspace_id == workspace_id,
                CanonicalCanvasObjectBinding.user_id == user_id,
                CanonicalCanvasObjectBinding.canvas_id == canvas_id,
            )
        )
        if binding is None:
            self._session.add(
                CanonicalCanvasObjectBinding(
                    binding_id=uuid.uuid4(),
                    object_id=reference.object_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    canvas_id=canvas_id,
                    created_by=user_id,
                    trace_id=trace_id,
                )
            )
            await self._flush("Knowledge graph canvas binding failed.")
        return entity

    async def _require_scope(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
    ) -> None:
        canvas = await self._session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.id == workspace_id,
                Workspace.owner_id == user_id,
                Workspace.lifecycle_state != "deleted",
                Workspace.deleted_at.is_(None),
            )
        )
        if canvas is None:
            raise CanonicalNotFoundError("Knowledge graph scope not found.")

    def _validate_relationship(
        self,
        relationship_type: str,
        source: CanonicalGraphEntity,
        target: CanonicalGraphEntity,
    ) -> None:
        compatibility = _RELATIONSHIP_COMPATIBILITY.get(relationship_type)
        if compatibility is None:
            raise CanonicalValidationError("Knowledge graph relationship type is not supported.")
        if source.object_id == target.object_id:
            raise CanonicalValidationError(
                "Knowledge graph relationships cannot reference themselves."
            )
        source_kinds, target_kinds = compatibility
        if source.entity_kind not in source_kinds or target.entity_kind not in target_kinds:
            raise CanonicalValidationError(
                "Knowledge graph relationship endpoints are incompatible."
            )

    async def _reject_existing_identity(
        self,
        workspace_id: uuid.UUID,
        relationship_type: str,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> None:
        existing = await self._session.scalar(
            select(CanonicalRelationship.object_id).where(
                CanonicalRelationship.workspace_id == workspace_id,
                CanonicalRelationship.relationship_type == relationship_type,
                CanonicalRelationship.source_object_id == source_id,
                CanonicalRelationship.target_object_id == target_id,
            )
        )
        if existing is not None:
            raise CanonicalConflictError("Knowledge graph relationship already exists.")

    async def _reject_cycle(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        relationship_type: str,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> None:
        rows = (
            await self._session.execute(
                select(
                    CanonicalRelationship.source_object_id,
                    CanonicalRelationship.target_object_id,
                )
                .join(
                    CanonicalGraphRelationship,
                    CanonicalGraphRelationship.relationship_id == CanonicalRelationship.object_id,
                )
                .join(
                    CanonicalObject,
                    CanonicalObject.id == CanonicalRelationship.object_id,
                )
                .where(
                    CanonicalGraphRelationship.user_id == user_id,
                    CanonicalGraphRelationship.workspace_id == workspace_id,
                    CanonicalGraphRelationship.canvas_id == canvas_id,
                    CanonicalRelationship.relationship_type == relationship_type,
                    CanonicalObject.lifecycle_state != "deleted",
                )
                .limit(MAX_CYCLE_CHECK_EDGES + 1)
            )
        ).all()
        if len(rows) > MAX_CYCLE_CHECK_EDGES:
            raise CanonicalConflictError("Knowledge graph cycle validation limit was exceeded.")
        adjacency: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for existing_source, existing_target in rows:
            adjacency[existing_source].append(existing_target)
        pending: deque[uuid.UUID] = deque([target_id])
        visited: set[uuid.UUID] = set()
        while pending:
            current = pending.popleft()
            if current == source_id:
                raise CanonicalValidationError("This relationship would create a prohibited cycle.")
            if current in visited:
                continue
            visited.add(current)
            pending.extend(adjacency[current])

    async def _advance_graph_revision(self, workspace_id: uuid.UUID) -> int:
        state = await self._session.scalar(
            select(WorkspaceGraphState)
            .where(WorkspaceGraphState.workspace_id == workspace_id)
            .with_for_update()
        )
        if state is None:
            state = WorkspaceGraphState(workspace_id=workspace_id, revision=0)
            self._session.add(state)
            await self._flush("Knowledge graph revision initialization failed.")
        state.revision += 1
        await self._flush("Knowledge graph revision update failed.")
        return state.revision

    async def _idempotent_create(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        idempotency_key: str,
        request_digest: str,
    ) -> GraphRelationshipRecord | None:
        graph = await self._session.scalar(
            select(CanonicalGraphRelationship).where(
                CanonicalGraphRelationship.user_id == user_id,
                CanonicalGraphRelationship.workspace_id == workspace_id,
                CanonicalGraphRelationship.canvas_id == canvas_id,
                CanonicalGraphRelationship.idempotency_key == idempotency_key,
            )
        )
        if graph is None:
            return None
        if graph.request_digest != request_digest:
            raise CanonicalConflictError(
                "The idempotency key was already used for a different graph mutation."
            )
        return await self.get_relationship(
            user_id,
            workspace_id,
            canvas_id,
            graph.relationship_id,
        )

    async def _latest_history(
        self, relationship_id: uuid.UUID
    ) -> CanonicalRelationshipHistory | None:
        statement: Select[tuple[CanonicalRelationshipHistory]] = select(
            CanonicalRelationshipHistory
        )
        result = await self._session.execute(
            statement.where(CanonicalRelationshipHistory.relationship_id == relationship_id)
            .order_by(
                CanonicalRelationshipHistory.graph_revision.desc(),
                CanonicalRelationshipHistory.history_id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _run_traced(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        object_id: uuid.UUID,
        operation: str,
        event_type: str,
        source_identity: str,
        parent_trace_id: uuid.UUID | None,
        mutation: Callable[[TraceContext], Awaitable[GraphRelationshipRecord]],
    ) -> GraphRelationshipRecord:
        actor_id = str(user_id)
        try:
            context = await self._trace.start_trace(
                StartTraceInput(
                    parent_trace_id=parent_trace_id,
                    event_type=f"{operation}.started",
                    actor_id=actor_id,
                    actor_type="user",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    object_id=object_id,
                    object_type="knowledge_graph_relationship",
                    operation=operation,
                )
            )
        except TracePersistenceError as exc:
            raise CanonicalStorageError("Knowledge graph trace persistence failed.") from exc
        try:
            async with self._session.begin_nested():
                result = await mutation(context)
                await self._trace.complete_trace(
                    CompleteTraceInput(
                        trace_id=context.trace_id,
                        parent_trace_id=context.parent_trace_id,
                        event_type=f"{operation}.succeeded",
                        actor_id=actor_id,
                        actor_type="user",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        object_id=result.graph.relationship_id,
                        object_type="knowledge_graph_relationship",
                        operation=operation,
                        metadata={"graphRevision": result.current_history.graph_revision},
                    )
                )
                event_payload: dict[str, JsonValue] = {
                    "relationshipType": result.relationship.relationship_type,
                    "state": result.current_history.state,
                    "graphRevision": result.current_history.graph_revision,
                }
                if result.current_history.reason_code is not None:
                    event_payload["reasonCode"] = result.current_history.reason_code
                await self._events.record(
                    CreateDomainEvent(
                        event_type=event_type,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        canvas_id=canvas_id,
                        subject_id=result.graph.relationship_id,
                        related_id=result.current_history.history_id,
                        actor_user_id=user_id,
                        source_identity=source_identity,
                        trace_id=context.trace_id,
                        payload=event_payload,
                        origin_type="authenticated_user",
                        graph_revision=result.current_history.graph_revision,
                        graph_relationship_id=result.graph.relationship_id,
                        graph_history_id=result.current_history.history_id,
                    )
                )
        except CanonicalDomainError as exc:
            await self._record_failure(context, user_id, workspace_id, object_id, operation, exc)
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            error = CanonicalStorageError("Knowledge graph persistence is temporarily unavailable.")
            await self._record_failure(context, user_id, workspace_id, object_id, operation, error)
            raise error from exc
        except TracePersistenceError as exc:
            error = CanonicalStorageError("Knowledge graph trace completion failed.")
            await self._record_failure(context, user_id, workspace_id, object_id, operation, error)
            raise error from exc
        except DomainEventError as exc:
            error = CanonicalStorageError("Knowledge graph event persistence failed.")
            await self._record_failure(context, user_id, workspace_id, object_id, operation, error)
            raise error from exc
        return result

    async def _record_failure(
        self,
        context: TraceContext,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        object_id: uuid.UUID,
        operation: str,
        error: CanonicalDomainError,
    ) -> None:
        try:
            await self._trace.fail_trace(
                FailTraceInput(
                    trace_id=context.trace_id,
                    parent_trace_id=context.parent_trace_id,
                    event_type=f"{operation}.failed",
                    actor_id=str(user_id),
                    actor_type="user",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    object_id=object_id,
                    object_type="knowledge_graph_relationship",
                    operation=operation,
                    error=TraceErrorInfo(
                        code=error.code,
                        message=error.safe_message,
                    ),
                )
            )
        except TracePersistenceError as exc:
            raise CanonicalStorageError(
                "Knowledge graph failure trace persistence failed."
            ) from exc

    async def _flush(self, message: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise CanonicalConflictError(
                "Knowledge graph mutation conflicts with existing state."
            ) from exc
        except SQLAlchemyError as exc:
            raise CanonicalStorageError(message) from exc


def _digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_replayed(record: GraphRelationshipRecord) -> GraphRelationshipRecord:
    return GraphRelationshipRecord(
        graph=record.graph,
        relationship=record.relationship,
        object=record.object,
        provenance=record.provenance,
        current_history=record.current_history,
        source=record.source,
        target=record.target,
        replayed=True,
    )


__all__ = [
    "GRAPH_ENTITY_KINDS",
    "GRAPH_RELATIONSHIP_TYPES",
    "CreateGraphRelationship",
    "DeactivateGraphRelationship",
    "GraphEntityKind",
    "GraphEntityReference",
    "GraphHistoryState",
    "GraphRelationshipRecord",
    "GraphRelationshipType",
    "KnowledgeGraphService",
]
