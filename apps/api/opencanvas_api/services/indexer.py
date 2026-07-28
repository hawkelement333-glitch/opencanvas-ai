from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import multiprocessing
import re
import socket
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal, cast

from pydantic import JsonValue
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opencanvas_api.core.config import AppMode, Settings
from opencanvas_api.db.models import (
    Canvas,
    Document,
    DocumentChunk,
    DocumentEmbedding,
    DocumentVersion,
    IndexerAuditEvent,
    IndexerFailure,
    IndexPublication,
    IndexRevision,
    IndexRevisionChunk,
    IngestionRequest,
    IngestionRequestTransition,
    NormalizedArtifact,
    PipelineManifest,
    RetrievalHead,
    VectorMaterialization,
    Workspace,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration_resources import (
    ShareAccessLevel,
    ShareResourceKind,
    SharingService,
)
from opencanvas_api.services.documents.chunking import chunk_document
from opencanvas_api.services.documents.embeddings import EmbeddingProvider
from opencanvas_api.services.documents.errors import DocumentServiceError
from opencanvas_api.services.documents.extraction import ExtractedDocument, extract_document
from opencanvas_api.services.documents.storage import DocumentStorage
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    FailTraceInput,
    StartTraceInput,
    TraceErrorInfo,
    TraceService,
)

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_TERMINAL_STATES = frozenset({"published", "failed", "canceled", "superseded"})
_FAILURE_REGISTRY = frozenset(
    {
        "unsupported_format",
        "corrupt_source",
        "parser_crash",
        "parser_timeout",
        "parser_resource_limit",
        "normalization_failed",
        "metadata_extraction_failed",
        "embedding_failed",
        "nondeterministic_dependency_output",
        "storage_unavailable",
        "database_unavailable",
        "authority_revoked",
        "membership_revoked",
        "resource_revoked",
        "source_changed",
        "superseded",
        "canceled",
        "publication_conflict",
        "publication_disabled",
        "internal_safe_failure",
    }
)


class IndexerError(RuntimeError):
    def __init__(
        self,
        safe_message: str,
        *,
        code: str = "indexer_failed",
        status_code: int = 409,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.code = code
        self.status_code = status_code


class IndexerNotFoundError(IndexerError):
    def __init__(self) -> None:
        super().__init__(
            "The index operation was not found.",
            code="index_not_found",
            status_code=404,
        )


class IndexerConflictError(IndexerError):
    def __init__(
        self,
        safe_message: str = "The index operation conflicts with current state.",
    ) -> None:
        super().__init__(safe_message, code="index_conflict", status_code=409)


@dataclass(frozen=True, slots=True)
class IndexerHooks:
    after_revision: Callable[[], Awaitable[None] | None] | None = None
    after_publication: Callable[[], Awaitable[None] | None] | None = None


@dataclass(frozen=True, slots=True)
class IngestionView:
    request: IngestionRequest
    transition: IngestionRequestTransition
    revision: IndexRevision | None
    publication: IndexPublication | None
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class _Scope:
    workspace: Workspace
    canvas: Canvas
    document: Document
    version: DocumentVersion
    membership_id: uuid.UUID
    authority_generation: int


class PipelineManifestService:
    def __init__(self, settings: Settings, provider: EmbeddingProvider) -> None:
        self.settings = settings
        self.provider = provider

    async def resolve(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        document_version_id: uuid.UUID,
        source_sha256: str,
        file_type: str,
    ) -> PipelineManifest:
        del document_version_id, source_sha256
        configuration: dict[str, JsonValue] = {
            "fileType": file_type,
            "parserTimeoutSeconds": self.settings.indexer_parser_timeout_seconds,
            "parserMemoryLimitBytes": self.settings.indexer_parser_memory_limit_bytes,
            "parserCpuSeconds": self.settings.indexer_parser_cpu_seconds,
            "maxPdfPages": self.settings.document_max_pdf_pages,
            "maxExtractedCharacters": self.settings.document_max_extracted_characters,
            "chunkSize": self.settings.document_chunk_size_chars,
            "chunkOverlap": self.settings.document_chunk_overlap_chars,
            "embeddingBatchSize": self.settings.embedding_batch_size,
        }
        manifest_values: dict[str, JsonValue] = {
            "schemaVersion": self.settings.indexer_manifest_schema_version,
            "parserName": f"mobius-{file_type}",
            "parserVersion": self.settings.indexer_parser_version,
            "parserBuildDigest": self.settings.indexer_parser_build_digest,
            "normalizerVersion": self.settings.indexer_normalizer_version,
            "metadataVersion": self.settings.indexer_metadata_version,
            "chunkerVersion": self.settings.indexer_chunker_version,
            "embeddingProvider": self.provider.name,
            "embeddingModel": self.provider.model,
            "embeddingConfigurationVersion": self.provider.configuration_version,
            "dimensions": self.provider.dimensions,
            "indexerVersion": self.settings.indexer_version,
            "indexSchemaVersion": self.settings.indexer_schema_version,
            "configuration": configuration,
        }
        manifest_digest = _digest(manifest_values)
        existing = await session.scalar(
            select(PipelineManifest).where(
                PipelineManifest.workspace_id == workspace_id,
                PipelineManifest.manifest_digest == manifest_digest,
            )
        )
        if existing is not None:
            return existing
        manifest = PipelineManifest(
            manifest_id=uuid.uuid5(workspace_id, f"pipeline-manifest:{manifest_digest}"),
            workspace_id=workspace_id,
            schema_version=self.settings.indexer_manifest_schema_version,
            manifest_digest=manifest_digest,
            parser_name=f"mobius-{file_type}",
            parser_version=self.settings.indexer_parser_version,
            parser_build_digest=self.settings.indexer_parser_build_digest,
            normalizer_version=self.settings.indexer_normalizer_version,
            metadata_version=self.settings.indexer_metadata_version,
            chunker_version=self.settings.indexer_chunker_version,
            embedding_provider=self.provider.name,
            embedding_model=self.provider.model,
            embedding_configuration_version=self.provider.configuration_version,
            dimensions=self.provider.dimensions,
            indexer_version=self.settings.indexer_version,
            index_schema_version=self.settings.indexer_schema_version,
            configuration_payload=cast(dict[str, object], configuration),
            created_at=datetime.now(UTC),
        )
        session.add(manifest)
        await session.flush()
        return manifest


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        storage: DocumentStorage,
        provider: EmbeddingProvider,
        hooks: IndexerHooks | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.provider = provider
        self.hooks = hooks or IndexerHooks()
        self.trace = TraceService(session)
        self.events = DomainEventService(session)
        self.manifests = PipelineManifestService(settings, provider)

    async def request(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        document_id: uuid.UUID,
        document_version: int,
        idempotency_key: str,
        operation: Literal["index", "reindex"] = "index",
    ) -> IngestionView:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise IndexerError(
                "A valid idempotency key is required.",
                code="idempotency_key_invalid",
                status_code=422,
            )
        scope = await self._scope(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=document_version,
            access_level=ShareAccessLevel.CONTRIBUTE,
        )
        manifest = await self.manifests.resolve(
            self.session,
            workspace_id=workspace_id,
            document_version_id=scope.version.id,
            source_sha256=scope.version.content_sha256,
            file_type=scope.version.file_type,
        )
        request_digest = _digest(
            {
                "operation": operation,
                "userId": str(principal.user_id),
                "membershipId": str(scope.membership_id),
                "workspaceId": str(workspace_id),
                "canvasId": str(canvas_id),
                "documentId": str(document_id),
                "documentVersionId": str(scope.version.id),
                "documentVersion": document_version,
                "sourceSha256": scope.version.content_sha256,
                "manifestDigest": manifest.manifest_digest,
            }
        )
        existing = await self.session.scalar(
            select(IngestionRequest).where(
                IngestionRequest.user_id == principal.user_id,
                IngestionRequest.workspace_id == workspace_id,
                IngestionRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise IndexerConflictError("The idempotency key was reused for another request.")
            view = await self._view(existing, principal=principal)
            return IngestionView(
                view.request,
                view.transition,
                view.revision,
                view.publication,
                duplicate=True,
            )
        if await self._active_request_count(workspace_id) >= (
            self.settings.indexer_max_active_requests_per_workspace
        ):
            raise IndexerError(
                "The workspace has reached its active indexing limit.",
                code="indexing_limit_reached",
                status_code=429,
            )
        now = datetime.now(UTC)
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="indexer.ingestion",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=request_id,
                object_type="ingestion_request",
                operation=f"{operation}_request",
                metadata={
                    "documentVersion": document_version,
                    "manifestVersion": manifest.schema_version,
                },
            )
        )
        request = IngestionRequest(
            request_id=request_id,
            user_id=principal.user_id,
            membership_id=scope.membership_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version_id=scope.version.id,
            document_version=document_version,
            operation=operation,
            pipeline_manifest_id=manifest.manifest_id,
            authority_generation=scope.authority_generation,
            cancel_generation=0,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            source_sha256=scope.version.content_sha256,
            trace_id=trace_id,
            created_at=now,
        )
        requested = self._transition(
            request=request,
            sequence=0,
            previous=None,
            current="requested",
            reason="request_accepted",
            actor_user_id=principal.user_id,
            cancel_generation=0,
            now=now,
        )
        queued = self._transition(
            request=request,
            sequence=1,
            previous="requested",
            current="queued",
            reason="request_queued",
            actor_user_id=principal.user_id,
            cancel_generation=0,
            now=now,
        )
        self.session.add(request)
        await self.session.flush()
        self.session.add_all((requested, queued))
        audit = self._audit(
            request=request,
            action=f"{operation}.request",
            outcome="allowed",
            reason_code="request_queued",
            metadata={"documentVersion": document_version},
            now=now,
        )
        self.session.add(audit)
        await self._event(
            request=request,
            event_type=(
                "index.reindex.requested" if operation == "reindex" else "ingestion.requested"
            ),
            subject_id=request_id,
            source=f"{operation}:requested",
            payload={
                "state": "requested",
                "documentId": str(document_id),
                "documentVersion": document_version,
                "manifestVersion": manifest.schema_version,
            },
            audit_event_id=audit.audit_event_id,
        )
        await self._event(
            request=request,
            event_type="ingestion.queued",
            subject_id=request_id,
            source=f"{operation}:queued",
            payload={
                "state": "queued",
                "documentId": str(document_id),
                "documentVersion": document_version,
            },
            audit_event_id=audit.audit_event_id,
        )
        await self.session.flush()
        return IngestionView(request, queued, None, None)

    async def get(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> IngestionView:
        request = await self.session.scalar(
            select(IngestionRequest).where(
                IngestionRequest.request_id == request_id,
                IngestionRequest.workspace_id == workspace_id,
                IngestionRequest.canvas_id == canvas_id,
            )
        )
        if request is None:
            raise IndexerNotFoundError()
        await self._scope(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=request.document_id,
            document_version=request.document_version,
            access_level=ShareAccessLevel.VIEW,
        )
        return await self._view(request, principal=principal)

    async def cancel(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> IngestionView:
        view = await self.get(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            request_id=request_id,
        )
        await self._scope(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=view.request.document_id,
            document_version=view.request.document_version,
            access_level=ShareAccessLevel.CONTRIBUTE,
        )
        if view.transition.current_state in _TERMINAL_STATES:
            if view.transition.current_state == "canceled":
                return view
            raise IndexerConflictError("A terminal index request cannot be canceled.")
        now = datetime.now(UTC)
        canceled = self._transition(
            request=view.request,
            sequence=view.transition.sequence + 1,
            previous=view.transition.current_state,
            current="canceled",
            reason="user_canceled",
            actor_user_id=principal.user_id,
            cancel_generation=view.transition.cancel_generation + 1,
            now=now,
        )
        self.session.add(canceled)
        audit = self._audit(
            request=view.request,
            action="ingestion.cancel",
            outcome="succeeded",
            reason_code="user_canceled",
            metadata={"previousState": view.transition.current_state},
            now=now,
        )
        self.session.add(audit)
        await self._event(
            request=view.request,
            event_type="ingestion.canceled",
            subject_id=view.request.request_id,
            source=f"canceled:{canceled.sequence}",
            payload={
                "state": "canceled",
                "reasonCode": "user_canceled",
                "documentId": str(view.request.document_id),
                "documentVersion": view.request.document_version,
            },
            audit_event_id=audit.audit_event_id,
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=view.request.trace_id,
                event_type="indexer.ingestion",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=request_id,
                object_type="ingestion_request",
                operation="ingestion_cancel",
                metadata={"state": "canceled"},
            )
        )
        await self.session.flush()
        return IngestionView(view.request, canceled, view.revision, view.publication)

    async def list_revisions(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        document_id: uuid.UUID,
        limit: int = 50,
    ) -> list[IndexRevision]:
        if not 1 <= limit <= 100:
            raise IndexerError("The revision limit is invalid.", status_code=422)
        document = await self.session.get(Document, document_id)
        if document is None:
            raise IndexerNotFoundError()
        await self._scope(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version=document.current_version,
            access_level=ShareAccessLevel.VIEW,
        )
        return list(
            (
                await self.session.scalars(
                    select(IndexRevision)
                    .where(
                        IndexRevision.workspace_id == workspace_id,
                        IndexRevision.canvas_id == canvas_id,
                        IndexRevision.document_id == document_id,
                    )
                    .order_by(IndexRevision.created_at.desc(), IndexRevision.revision_id)
                    .limit(limit)
                )
            ).all()
        )

    async def build(self, request_id: uuid.UUID) -> IndexRevision | None:
        request = await self.session.get(IngestionRequest, request_id)
        if request is None:
            raise IndexerNotFoundError()
        transition = await self._latest_transition(request_id)
        if transition.current_state in _TERMINAL_STATES:
            return cast(
                IndexRevision | None,
                await self.session.scalar(
                    select(IndexRevision).where(IndexRevision.request_id == request_id)
                ),
            )
        version = await self.session.get(DocumentVersion, request.document_version_id)
        manifest = await self.session.get(PipelineManifest, request.pipeline_manifest_id)
        if version is None or manifest is None:
            raise IndexerError("The immutable source or pipeline manifest is unavailable.")
        try:
            content = await self.storage.read(version.storage_key)
        except Exception as exc:
            raise IndexerError(
                "The source storage is unavailable.",
                code="storage_unavailable",
                status_code=503,
            ) from exc
        if hashlib.sha256(content).hexdigest() != request.source_sha256:
            raise IndexerError("The source changed.", code="source_changed")
        extracted = await parse_isolated(
            file_type=version.file_type,
            content=content,
            settings=self.settings,
        )
        chunks = chunk_document(
            extracted,
            chunk_size=self.settings.document_chunk_size_chars,
            overlap=self.settings.document_chunk_overlap_chars,
        )
        if not chunks:
            raise IndexerError("No indexable passages were produced.", code="corrupt_source")
        normalized_digest = _sha(extracted.text)
        prior_revision = await self.session.scalar(
            select(IndexRevision)
            .where(
                IndexRevision.workspace_id == request.workspace_id,
                IndexRevision.pipeline_manifest_id == request.pipeline_manifest_id,
                IndexRevision.source_sha256 == request.source_sha256,
            )
            .order_by(IndexRevision.created_at, IndexRevision.revision_id)
            .limit(1)
        )
        deduplication_kind = "exact_bytes"
        if prior_revision is None:
            prior_revision = await self.session.scalar(
                select(IndexRevision)
                .where(
                    IndexRevision.workspace_id == request.workspace_id,
                    IndexRevision.pipeline_manifest_id == request.pipeline_manifest_id,
                    IndexRevision.normalized_digest == normalized_digest,
                )
                .order_by(IndexRevision.created_at, IndexRevision.revision_id)
                .limit(1)
            )
            deduplication_kind = "normalized_content"
        reused_materializations: list[uuid.UUID | None]
        if prior_revision is None:
            deduplication_kind = "none"
            vectors = await self.provider.embed([chunk.content for chunk in chunks])
            reused_materializations = [None] * len(chunks)
        else:
            prior_chunks = list(
                (
                    await self.session.scalars(
                        select(IndexRevisionChunk)
                        .where(IndexRevisionChunk.revision_id == prior_revision.revision_id)
                        .order_by(IndexRevisionChunk.chunk_index)
                    )
                ).all()
            )
            prior_vectors = {
                row.chunk_id: row
                for row in (
                    await self.session.scalars(
                        select(VectorMaterialization).where(
                            VectorMaterialization.revision_id == prior_revision.revision_id
                        )
                    )
                ).all()
            }
            prior_signatures = [
                (
                    row.chunk_index,
                    row.content_digest,
                    row.page_number,
                    row.heading,
                    row.char_start,
                    row.char_end,
                )
                for row in prior_chunks
            ]
            current_signatures = [
                (
                    row.chunk_index,
                    _sha(row.content),
                    row.page_number,
                    row.heading,
                    row.char_start,
                    row.char_end,
                )
                for row in chunks
            ]
            if prior_signatures != current_signatures or len(prior_vectors) != len(prior_chunks):
                raise IndexerError(
                    "The dependency output drifted under an unchanged manifest.",
                    code="nondeterministic_dependency_output",
                )
            ordered_prior_vectors = [prior_vectors[row.chunk_id] for row in prior_chunks]
            if any(
                row.provider != self.provider.name
                or row.model != self.provider.model
                or row.dimensions != self.provider.dimensions
                for row in ordered_prior_vectors
            ):
                raise IndexerError(
                    "The dependency output drifted under an unchanged manifest.",
                    code="nondeterministic_dependency_output",
                )
            vectors = [list(row.embedding) for row in ordered_prior_vectors]
            reused_materializations = [row.materialization_id for row in ordered_prior_vectors]
        if len(vectors) != len(chunks):
            raise IndexerError(
                "The embedding provider returned an incomplete result.",
                code="embedding_failed",
                status_code=502,
            )
        metadata: dict[str, JsonValue] = {
            "fileType": version.file_type,
            "pageCount": extracted.page_count,
            "chunkCount": len(chunks),
        }
        metadata_digest = _digest(metadata)
        near_duplicate = _sha(" ".join(extracted.text.casefold().split()))
        chunk_values = [
            {
                "index": chunk.chunk_index,
                "digest": _sha(chunk.content),
                "page": chunk.page_number,
                "heading": chunk.heading,
                "start": chunk.char_start,
                "end": chunk.char_end,
            }
            for chunk in chunks
        ]
        chunk_manifest_digest = _digest({"chunks": cast(list[JsonValue], chunk_values)})
        vector_digests = [_vector_digest(vector) for vector in vectors]
        vector_manifest_digest = _digest({"vectors": cast(list[JsonValue], vector_digests)})
        previous_vector_digest = await self.session.scalar(
            select(IndexRevision.vector_manifest_digest)
            .where(
                IndexRevision.workspace_id == request.workspace_id,
                IndexRevision.document_version_id == request.document_version_id,
                IndexRevision.pipeline_manifest_id == request.pipeline_manifest_id,
            )
            .order_by(IndexRevision.created_at)
            .limit(1)
        )
        if previous_vector_digest is not None and previous_vector_digest != vector_manifest_digest:
            raise IndexerError(
                "The dependency output drifted under an unchanged manifest.",
                code="nondeterministic_dependency_output",
            )
        output_digest = _digest(
            {
                "source": request.source_sha256,
                "normalized": normalized_digest,
                "metadata": metadata_digest,
                "chunks": chunk_manifest_digest,
                "vectors": vector_manifest_digest,
                "manifest": manifest.manifest_digest,
            }
        )
        now = datetime.now(UTC)
        revision_id = uuid.uuid5(request.request_id, f"revision:{output_digest}")
        artifact = NormalizedArtifact(
            artifact_id=uuid.uuid5(request.request_id, "normalized-artifact"),
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            pipeline_manifest_id=request.pipeline_manifest_id,
            normalized_text=extracted.text,
            normalized_digest=normalized_digest,
            metadata_payload=cast(dict[str, object], metadata),
            metadata_digest=metadata_digest,
            near_duplicate_fingerprint=near_duplicate,
            created_at=now,
        )
        revision = IndexRevision(
            revision_id=revision_id,
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            canvas_id=request.canvas_id,
            document_id=request.document_id,
            document_version_id=request.document_version_id,
            document_version=request.document_version,
            pipeline_manifest_id=request.pipeline_manifest_id,
            revision_kind="native",
            status="completed",
            deduplication_kind=deduplication_kind,
            deduplicated_from_revision_id=(
                prior_revision.revision_id if prior_revision is not None else None
            ),
            source_sha256=request.source_sha256,
            normalized_digest=normalized_digest,
            metadata_digest=metadata_digest,
            chunk_manifest_digest=chunk_manifest_digest,
            vector_manifest_digest=vector_manifest_digest,
            output_digest=output_digest,
            created_by_user_id=request.user_id,
            trace_id=request.trace_id,
            created_at=now,
        )
        self.session.add_all((artifact, revision))
        await self.session.flush()
        chunk_rows: list[IndexRevisionChunk] = []
        vector_rows: list[VectorMaterialization] = []
        for chunk, vector, vector_digest, reused_from in zip(
            chunks,
            vectors,
            vector_digests,
            reused_materializations,
            strict=True,
        ):
            content_digest = _sha(chunk.content)
            stable_id = uuid.uuid5(
                request.workspace_id,
                (
                    f"index-chunk:{request.document_version_id}:"
                    f"{manifest.manifest_digest}:{chunk.chunk_index}:{content_digest}"
                ),
            )
            revision_chunk_id = uuid.uuid5(revision_id, f"chunk:{chunk.chunk_index}:{stable_id}")
            chunk_rows.append(
                IndexRevisionChunk(
                    chunk_id=revision_chunk_id,
                    stable_chunk_id=stable_id,
                    revision_id=revision_id,
                    workspace_id=request.workspace_id,
                    document_id=request.document_id,
                    document_version=request.document_version,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_digest=content_digest,
                    page_number=chunk.page_number,
                    heading=chunk.heading,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    created_at=now,
                )
            )
            vector_rows.append(
                VectorMaterialization(
                    materialization_id=uuid.uuid5(
                        revision_id, f"vector:{chunk.chunk_index}:{vector_digest}"
                    ),
                    revision_id=revision_id,
                    workspace_id=request.workspace_id,
                    chunk_id=revision_chunk_id,
                    reused_from_materialization_id=reused_from,
                    provider=self.provider.name,
                    model=self.provider.model,
                    dimensions=self.provider.dimensions,
                    embedding=vector,
                    artifact_digest=vector_digest,
                    created_at=now,
                )
            )
        self.session.add_all(chunk_rows)
        await self.session.flush()
        self.session.add_all(vector_rows)
        states = ("parsing", "normalizing", "chunking", "indexing", "completed")
        previous = transition.current_state
        sequence = transition.sequence
        for state in states:
            sequence += 1
            current = self._transition(
                request=request,
                sequence=sequence,
                previous=previous,
                current=state,
                reason=f"{state}_completed" if state == "completed" else f"{state}_started",
                actor_user_id=request.user_id,
                cancel_generation=transition.cancel_generation,
                now=now,
            )
            self.session.add(current)
            previous = state
        audit = self._audit(
            request=request,
            action="index.build",
            outcome="succeeded",
            reason_code="revision_created",
            metadata={"revisionId": str(revision_id), "chunkCount": len(chunks)},
            now=now,
        )
        self.session.add(audit)
        await self._event(
            request=request,
            event_type="index.revision.created",
            subject_id=revision_id,
            source=f"revision:{output_digest}",
            payload={
                "state": "completed",
                "documentId": str(request.document_id),
                "documentVersion": request.document_version,
                "revisionId": str(revision_id),
                "manifestVersion": manifest.schema_version,
            },
            audit_event_id=audit.audit_event_id,
        )
        await _run_hook(self.hooks.after_revision)
        await self.session.flush()
        return revision

    async def publish(
        self, request_id: uuid.UUID, revision_id: uuid.UUID
    ) -> IndexPublication | None:
        if self.settings.indexer_publication_mode == "disabled":
            return None
        if self.settings.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}:
            raise IndexerError(
                "Indexer publication is disabled until the clean-object gate is available.",
                code="publication_disabled",
                status_code=503,
            )
        request = await self.session.get(IngestionRequest, request_id)
        revision = await self.session.get(IndexRevision, revision_id)
        if (
            request is None
            or revision is None
            or revision.request_id != request_id
            or revision.workspace_id != request.workspace_id
        ):
            raise IndexerNotFoundError()
        locked_document_id = await self.session.scalar(
            select(Document.id).where(Document.id == request.document_id).with_for_update()
        )
        if locked_document_id is None:
            raise IndexerNotFoundError()
        existing = await self.session.scalar(
            select(IndexPublication).where(
                IndexPublication.workspace_id == request.workspace_id,
                IndexPublication.document_id == request.document_id,
                IndexPublication.revision_id == revision_id,
            )
        )
        if existing is not None:
            return existing
        transition = await self._latest_transition(request_id)
        if transition.current_state != "completed":
            raise IndexerConflictError("Only a completed revision can be published.")
        principal = Principal(
            user_id=request.user_id,
            email="indexer-internal@mobius.invalid",
            display_name="Indexer request actor",
            session_id=None,
            csrf_token_hash=None,
            synthetic=True,
        )
        try:
            scope = await self._scope(
                principal=principal,
                workspace_id=request.workspace_id,
                canvas_id=request.canvas_id,
                document_id=request.document_id,
                document_version=request.document_version,
                access_level=ShareAccessLevel.CONTRIBUTE,
                expected_authority_generation=request.authority_generation,
            )
        except IndexerNotFoundError as exc:
            raise IndexerError(
                "The indexing authority is no longer current.",
                code="authority_revoked",
            ) from exc
        if (
            scope.version.id != request.document_version_id
            or scope.version.content_sha256 != request.source_sha256
            or scope.document.current_version != request.document_version
            or scope.document.deleted_at is not None
            or scope.document.status in {"deleting", "deleted"}
        ):
            raise IndexerError("The source changed.", code="source_changed")
        head = await self.session.scalar(
            select(RetrievalHead)
            .where(RetrievalHead.document_id == request.document_id)
            .with_for_update()
        )
        generation = (head.generation if head is not None else 0) + 1
        now = datetime.now(UTC)
        publication = IndexPublication(
            publication_id=uuid.uuid5(
                revision_id, f"publication:{generation}:{request.authority_generation}"
            ),
            revision_id=revision_id,
            workspace_id=request.workspace_id,
            canvas_id=request.canvas_id,
            document_id=request.document_id,
            generation=generation,
            actor_user_id=request.user_id,
            membership_id=request.membership_id,
            authority_generation=request.authority_generation,
            cancel_generation=transition.cancel_generation,
            trace_id=request.trace_id,
            published_at=now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(publication)
                await self.session.flush((publication,))
        except IntegrityError as exc:
            existing = cast(
                IndexPublication | None,
                await self.session.scalar(
                    select(IndexPublication).where(
                        IndexPublication.workspace_id == request.workspace_id,
                        IndexPublication.document_id == request.document_id,
                        IndexPublication.revision_id == revision_id,
                    )
                ),
            )
            if existing is not None:
                return existing
            raise IndexerError(
                "A concurrent publication changed the retrieval head.",
                code="publication_conflict",
            ) from exc
        chunks = list(
            (
                await self.session.scalars(
                    select(IndexRevisionChunk)
                    .where(IndexRevisionChunk.revision_id == revision_id)
                    .order_by(IndexRevisionChunk.chunk_index)
                )
            ).all()
        )
        vectors = {
            row.chunk_id: row
            for row in (
                await self.session.scalars(
                    select(VectorMaterialization).where(
                        VectorMaterialization.revision_id == revision_id
                    )
                )
            ).all()
        }
        if not chunks or len(vectors) != len(chunks):
            raise IndexerError("The revision evidence is incomplete.")
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == request.document_id)
        )
        projection_chunks = [
            DocumentChunk(
                id=chunk.stable_chunk_id,
                document_id=request.document_id,
                document_version=request.document_version,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                page_number=chunk.page_number,
                heading=chunk.heading,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
            )
            for chunk in chunks
        ]
        self.session.add_all(projection_chunks)
        await self.session.flush()
        self.session.add_all(
            DocumentEmbedding(
                document_id=request.document_id,
                chunk_id=chunk.stable_chunk_id,
                provider=vectors[chunk.chunk_id].provider,
                model=vectors[chunk.chunk_id].model,
                dimensions=vectors[chunk.chunk_id].dimensions,
                embedding=vectors[chunk.chunk_id].embedding,
            )
            for chunk in chunks
        )
        artifact = await self.session.scalar(
            select(NormalizedArtifact).where(NormalizedArtifact.request_id == request_id)
        )
        if artifact is None:
            raise IndexerError("The normalized artifact is unavailable.")
        scope.document.extracted_text = artifact.normalized_text
        scope.document.chunk_count = len(chunks)
        scope.document.page_count = cast(int | None, artifact.metadata_payload.get("pageCount"))
        scope.document.status = "ready"
        scope.document.processing_stage = "ready"
        scope.document.error_message = None
        scope.document.safe_error_category = None
        scope.version.extracted_text = artifact.normalized_text
        scope.version.status = "ready"
        if head is None:
            head = RetrievalHead(
                document_id=request.document_id,
                workspace_id=request.workspace_id,
                canvas_id=request.canvas_id,
                activation_kind="native",
                revision_id=revision_id,
                publication_id=publication.publication_id,
                compatibility_projection_id=None,
                generation=generation,
            )
            self.session.add(head)
        else:
            head.activation_kind = "native"
            head.revision_id = revision_id
            head.publication_id = publication.publication_id
            head.compatibility_projection_id = None
            head.generation = generation
        published = self._transition(
            request=request,
            sequence=transition.sequence + 1,
            previous="completed",
            current="published",
            reason="publication_committed",
            actor_user_id=request.user_id,
            cancel_generation=transition.cancel_generation,
            now=now,
        )
        self.session.add(published)
        audit = self._audit(
            request=request,
            action="index.publish",
            outcome="succeeded",
            reason_code="publication_committed",
            metadata={
                "revisionId": str(revision_id),
                "publicationId": str(publication.publication_id),
                "generation": generation,
            },
            now=now,
        )
        self.session.add(audit)
        await self._event(
            request=request,
            event_type="index.published",
            subject_id=publication.publication_id,
            source=f"publication:{generation}",
            payload={
                "state": "published",
                "documentId": str(request.document_id),
                "documentVersion": request.document_version,
                "revisionId": str(revision_id),
                "publicationId": str(publication.publication_id),
                "generation": generation,
            },
            audit_event_id=audit.audit_event_id,
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=request.trace_id,
                event_type="indexer.ingestion",
                actor_id=str(request.user_id),
                actor_type="service",
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                object_id=request.request_id,
                object_type="ingestion_request",
                operation="index_publication",
                metadata={
                    "state": "published",
                    "revisionId": str(revision_id),
                    "generation": generation,
                },
            )
        )
        await _run_hook(self.hooks.after_publication)
        await self.session.flush()
        return publication

    async def record_failure(self, request_id: uuid.UUID, error: Exception) -> None:
        request = await self.session.get(IngestionRequest, request_id)
        if request is None:
            return
        transition = await self._latest_transition(request_id)
        if transition.current_state in _TERMINAL_STATES:
            return
        code = (
            error.code
            if isinstance(error, IndexerError) and error.code in _FAILURE_REGISTRY
            else (
                error.code
                if isinstance(error, DocumentServiceError) and error.code in _FAILURE_REGISTRY
                else "internal_safe_failure"
            )
        )
        now = datetime.now(UTC)
        failed = self._transition(
            request=request,
            sequence=transition.sequence + 1,
            previous=transition.current_state,
            current="failed",
            reason=code,
            actor_user_id=request.user_id,
            cancel_generation=transition.cancel_generation,
            now=now,
        )
        failure = IndexerFailure(
            failure_id=uuid.uuid5(request_id, f"failure:{failed.sequence}:{code}"),
            request_id=request_id,
            workspace_id=request.workspace_id,
            safe_failure_code=code,
            retryable=code in {"storage_unavailable", "database_unavailable", "embedding_failed"},
            stage=transition.current_state,
            trace_id=request.trace_id,
            recorded_at=now,
        )
        audit = self._audit(
            request=request,
            action="index.build",
            outcome="failed",
            reason_code=code,
            metadata={"stage": transition.current_state},
            now=now,
        )
        self.session.add_all((failed, failure, audit))
        await self._event(
            request=request,
            event_type="ingestion.failed",
            subject_id=request_id,
            source=f"failed:{failed.sequence}:{code}",
            payload={
                "state": "failed",
                "reasonCode": code,
                "documentId": str(request.document_id),
                "documentVersion": request.document_version,
            },
            audit_event_id=audit.audit_event_id,
        )
        await self.trace.fail_trace(
            FailTraceInput(
                trace_id=request.trace_id,
                event_type="indexer.ingestion",
                actor_id=str(request.user_id),
                actor_type="service",
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                object_id=request.request_id,
                object_type="ingestion_request",
                operation="index_build",
                metadata={"state": "failed", "reasonCode": code},
                error=TraceErrorInfo(code=code, message="The index operation failed safely."),
            )
        )
        await self.session.flush()

    async def _scope(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        document_id: uuid.UUID,
        document_version: int,
        access_level: ShareAccessLevel,
        expected_authority_generation: int | None = None,
    ) -> _Scope:
        row = (
            await self.session.execute(
                select(Workspace, Canvas, Document, DocumentVersion)
                .join(Canvas, Canvas.workspace_id == Workspace.id)
                .join(Document, Document.canvas_id == Canvas.id)
                .join(
                    DocumentVersion,
                    DocumentVersion.document_id == Document.id,
                )
                .where(
                    Workspace.id == workspace_id,
                    Workspace.deleted_at.is_(None),
                    Workspace.lifecycle_state != "deleted",
                    Canvas.id == canvas_id,
                    Document.id == document_id,
                    Document.deleted_at.is_(None),
                    Document.status != "deleted",
                    DocumentVersion.version == document_version,
                )
            )
        ).one_or_none()
        if row is None:
            raise IndexerNotFoundError()
        access = await SharingService(self.session).evaluate_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=ShareResourceKind.CANVAS,
            resource_id=canvas_id,
            access_level=access_level,
            expected_authority_generation=expected_authority_generation,
        )
        if (
            not access.allowed
            or access.membership_id is None
            or access.authority_generation is None
        ):
            raise IndexerNotFoundError()
        return _Scope(
            row[0],
            row[1],
            row[2],
            row[3],
            access.membership_id,
            access.authority_generation,
        )

    async def _view(self, request: IngestionRequest, *, principal: Principal) -> IngestionView:
        del principal
        transition = await self._latest_transition(request.request_id)
        revision = await self.session.scalar(
            select(IndexRevision).where(IndexRevision.request_id == request.request_id)
        )
        publication = (
            await self.session.scalar(
                select(IndexPublication).where(IndexPublication.revision_id == revision.revision_id)
            )
            if revision is not None
            else None
        )
        return IngestionView(request, transition, revision, publication)

    async def _latest_transition(self, request_id: uuid.UUID) -> IngestionRequestTransition:
        transition = await self.session.scalar(
            select(IngestionRequestTransition)
            .where(IngestionRequestTransition.request_id == request_id)
            .order_by(IngestionRequestTransition.sequence.desc())
            .limit(1)
        )
        if transition is None:
            raise IndexerError("The ingestion lifecycle is incomplete.")
        return transition

    async def _active_request_count(self, workspace_id: uuid.UUID) -> int:
        latest = (
            select(func.max(IngestionRequestTransition.sequence))
            .where(IngestionRequestTransition.request_id == IngestionRequest.request_id)
            .correlate(IngestionRequest)
            .scalar_subquery()
        )
        return int(
            await self.session.scalar(
                select(func.count(IngestionRequest.request_id))
                .join(
                    IngestionRequestTransition,
                    (IngestionRequestTransition.request_id == IngestionRequest.request_id)
                    & (IngestionRequestTransition.sequence == latest),
                )
                .where(
                    IngestionRequest.workspace_id == workspace_id,
                    ~IngestionRequestTransition.current_state.in_(_TERMINAL_STATES),
                )
            )
            or 0
        )

    @staticmethod
    def _transition(
        *,
        request: IngestionRequest,
        sequence: int,
        previous: str | None,
        current: str,
        reason: str,
        actor_user_id: uuid.UUID,
        cancel_generation: int,
        now: datetime,
    ) -> IngestionRequestTransition:
        return IngestionRequestTransition(
            transition_id=uuid.uuid5(request.request_id, f"transition:{sequence}:{current}"),
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            sequence=sequence,
            previous_state=previous,
            current_state=current,
            reason_code=reason,
            actor_user_id=actor_user_id,
            authority_generation=request.authority_generation,
            cancel_generation=cancel_generation,
            trace_id=request.trace_id,
            recorded_at=now,
        )

    @staticmethod
    def _audit(
        *,
        request: IngestionRequest,
        action: str,
        outcome: str,
        reason_code: str,
        metadata: dict[str, object],
        now: datetime,
    ) -> IndexerAuditEvent:
        identity = _digest(
            {
                "requestId": str(request.request_id),
                "action": action,
                "outcome": outcome,
                "reason": reason_code,
                "metadata": cast(dict[str, JsonValue], metadata),
            }
        )
        return IndexerAuditEvent(
            audit_event_id=uuid.uuid5(request.request_id, f"audit:{identity}"),
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            actor_user_id=request.user_id,
            action=action,
            outcome=outcome,
            reason_code=reason_code,
            authority_generation=request.authority_generation,
            trace_id=request.trace_id,
            metadata_payload=metadata,
            recorded_at=now,
        )

    async def _event(
        self,
        *,
        request: IngestionRequest,
        event_type: str,
        subject_id: uuid.UUID,
        source: str,
        payload: dict[str, JsonValue],
        audit_event_id: uuid.UUID,
    ) -> None:
        owner_id = await self.session.scalar(
            select(Workspace.owner_id).where(Workspace.id == request.workspace_id)
        )
        if owner_id is None:
            raise IndexerNotFoundError()
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=owner_id,
                workspace_id=request.workspace_id,
                canvas_id=request.canvas_id,
                subject_id=subject_id,
                actor_user_id=request.user_id,
                source_identity=f"indexer:{request.request_id}:{source}"[:128],
                trace_id=request.trace_id,
                payload=payload,
                origin_type="authenticated_user",
                audit_event_id=audit_event_id,
            )
        )


async def process_ingestion_request(
    sessions: async_sessionmaker[AsyncSession],
    *,
    request_id: uuid.UUID,
    settings: Settings,
    storage: DocumentStorage,
    provider: EmbeddingProvider,
    hooks: IndexerHooks | None = None,
) -> None:
    revision_id: uuid.UUID | None = None
    try:
        async with sessions() as session:
            service = IngestionService(
                session,
                settings=settings,
                storage=storage,
                provider=provider,
                hooks=hooks,
            )
            revision = await service.build(request_id)
            if revision is None:
                await session.rollback()
                return
            revision_id = revision.revision_id
            await session.commit()
        async with sessions() as session:
            service = IngestionService(
                session,
                settings=settings,
                storage=storage,
                provider=provider,
                hooks=hooks,
            )
            await service.publish(request_id, revision_id)
            await session.commit()
    except Exception as exc:
        async with sessions() as session:
            service = IngestionService(
                session,
                settings=settings,
                storage=storage,
                provider=provider,
                hooks=hooks,
            )
            await service.record_failure(request_id, exc)
            await session.commit()


async def parse_isolated(
    *,
    file_type: str,
    content: bytes,
    settings: Settings,
) -> ExtractedDocument:
    parent, child = multiprocessing.get_context("spawn").Pipe(duplex=False)
    process = multiprocessing.get_context("spawn").Process(
        target=_parser_child,
        args=(
            child,
            file_type,
            content,
            settings.document_max_pdf_pages,
            settings.document_max_extracted_characters,
            settings.indexer_parser_memory_limit_bytes,
            settings.indexer_parser_cpu_seconds,
        ),
        daemon=True,
    )
    process.start()
    child.close()
    try:
        available = await asyncio.to_thread(parent.poll, settings.indexer_parser_timeout_seconds)
        if not available:
            process.terminate()
            process.join(timeout=2)
            raise IndexerError("The parser timed out.", code="parser_timeout", status_code=422)
        status, payload = parent.recv()
        process.join(timeout=2)
        if status != "ok":
            raise IndexerError(
                "The source could not be parsed safely.",
                code=cast(str, payload),
                status_code=422,
            )
        return cast(ExtractedDocument, payload)
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)


def _parser_child(
    connection: Any,
    file_type: str,
    content: bytes,
    max_pdf_pages: int,
    max_extracted_characters: int,
    memory_limit_bytes: int,
    cpu_seconds: int,
) -> None:
    try:
        try:
            resource_module = importlib.import_module("resource")
            resource_module.setrlimit(
                resource_module.RLIMIT_AS,
                (memory_limit_bytes, memory_limit_bytes),
            )
            resource_module.setrlimit(
                resource_module.RLIMIT_CPU,
                (cpu_seconds, cpu_seconds),
            )
        except (ImportError, OSError, ValueError):
            pass

        def _network_denied(*_args: object, **_kwargs: object) -> socket.socket:
            raise OSError("network access is disabled in the parser")

        socket.__dict__["socket"] = _network_denied
        settings = SimpleNamespace(
            document_max_pdf_pages=max_pdf_pages,
            document_max_extracted_characters=max_extracted_characters,
        )
        extracted = extract_document(
            file_type=file_type,
            content=content,
            settings=cast(Settings, settings),
        )
        connection.send(("ok", extracted))
    except DocumentServiceError as exc:
        code = "corrupt_source" if exc.code == "document_processing_failed" else exc.code
        connection.send(("error", code if code in _FAILURE_REGISTRY else "corrupt_source"))
    except BaseException:
        connection.send(("error", "parser_crash"))
    finally:
        connection.close()


async def _run_hook(
    hook: Callable[[], Awaitable[None] | None] | None,
) -> None:
    if hook is None:
        return
    result = hook()
    if result is not None:
        await result


def _digest(value: Mapping[str, JsonValue] | dict[str, JsonValue]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _vector_digest(vector: list[float]) -> str:
    return hashlib.sha256(
        json.dumps(
            [float(value) for value in vector],
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "IndexerConflictError",
    "IndexerError",
    "IndexerHooks",
    "IndexerNotFoundError",
    "IngestionService",
    "IngestionView",
    "PipelineManifestService",
    "parse_isolated",
    "process_ingestion_request",
]
