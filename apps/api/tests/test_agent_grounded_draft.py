from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    AIClaim,
    AIExecutionCitation,
    AIRequest,
    AIResponse,
    CanvasDocumentNode,
    CanvasNode,
    Citation,
    ControlledAgentExecutionState,
    ControlledAgentStateTransition,
    Document,
    DocumentChunk,
    DocumentEmbedding,
    DocumentVersion,
    UsageRecord,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.execution import (
    CancellationRequest,
    ControlledExecutionLifecycle,
)
from opencanvas_api.services.agents.grounded_draft import (
    ControlledDraftError,
    ControlledGroundedDraftService,
)
from opencanvas_api.services.ai import (
    AIProviderError,
    GroundedAIResult,
    GroundedCitation,
    GroundedSource,
    MockAIProvider,
)
from opencanvas_api.services.context import ContextBundle
from opencanvas_api.services.documents.embeddings import MockEmbeddingProvider
from tests.agent_fixtures import NOW
from tests.test_agent_authority_preflight import request_for
from tests.test_agent_immutable_context import _seed_selected_context


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
        auth_test_bypass=True,
    )


async def test_empty_document_card_prepares_and_runs_with_version_bound_extracted_evidence(
    database: Database,
) -> None:
    bundle, _, node, version, chunk = await _seed_selected_context(database)
    async with database.sessions() as session:
        stored_node = await session.get(CanvasNode, node.id)
        assert stored_node is not None
        stored_node.type = "document"
        stored_node.text = ""
        session.add(
            CanvasDocumentNode(
                node_id=node.id, canvas_id=node.canvas_id, document_id=version.document_id
            )
        )
        embedding = MockEmbeddingProvider()
        session.add(
            DocumentEmbedding(
                document_id=version.document_id,
                chunk_id=chunk.id,
                provider=embedding.name,
                model=embedding.model,
                dimensions=embedding.dimensions,
                embedding=(await embedding.embed([chunk.content]))[0],
            )
        )
        await session.commit()
        service = ControlledGroundedDraftService(
            session,
            provider=MockAIProvider(),
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        )
        prepared = await service.prepare(
            authenticated_user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            canvas_id=node.canvas_id,
            selected_node_ids=[node.id],
            instruction="What exact evidence was selected?",
            idempotency_key="document-card-version-bound",
            correlation_id="document-card-regression",
        )
        await session.commit()
        result = await service.execute(
            authenticated_user_id=bundle.execution.user_id, request=prepared.request
        )
        assert result.insufficient_evidence is False
        assert result.citations[0].document_id == version.document_id
        assert result.citations[0].document_version == version.version
        assert result.citations[0].chunk_id == chunk.id
        assert result.citations[0].quote == chunk.content
        request = await session.get(AIRequest, prepared.request.execution_id)
        assert request is not None
        selected = next(
            item for item in request.context_snapshot if item["resourceId"] == str(node.id)
        )
        assert selected["text"] == version.extracted_text
        assert stored_node.text == ""


class _RecordingGroundedProvider(MockAIProvider):
    instruction_seen: str | None = None
    notes_seen: ContextBundle | None = None
    sources_seen: list[GroundedSource] | None = None

    async def generate_grounded(
        self, instruction: str, notes_context: ContextBundle, sources: list[GroundedSource]
    ) -> GroundedAIResult:
        self.instruction_seen = instruction
        self.notes_seen = notes_context
        self.sources_seen = sources
        return await super().generate_grounded(instruction, notes_context, sources)


async def test_selected_current_version_is_filtered_before_top_k(database: Database) -> None:
    bundle, _, node, version, old_chunk = await _seed_selected_context(database)
    async with database.sessions() as session:
        stored_node = await session.get(CanvasNode, node.id)
        document = await session.get(Document, version.document_id)
        assert stored_node is not None and document is not None
        stored_node.type, stored_node.text = "document", ""
        document.current_version = 2
        current_version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            version=2,
            file_name=version.file_name,
            file_type=version.file_type,
            media_type=version.media_type,
            file_size_bytes=version.file_size_bytes,
            content_sha256=version.content_sha256,
            storage_key=f"test/{uuid.uuid4()}.txt",
            extracted_text=version.extracted_text,
            status="ready",
        )
        current_chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=document.id,
            document_version=2,
            chunk_index=1,
            content=old_chunk.content,
            heading=old_chunk.heading,
            char_start=0,
            char_end=len(old_chunk.content),
        )
        session.add_all(
            [
                current_version,
                current_chunk,
                CanvasDocumentNode(
                    node_id=node.id,
                    canvas_id=node.canvas_id,
                    document_id=document.id,
                ),
            ]
        )
        embedding = MockEmbeddingProvider()
        vector = (await embedding.embed([old_chunk.content]))[0]
        for chunk in [old_chunk, current_chunk]:
            session.add(
                DocumentEmbedding(
                    document_id=document.id,
                    chunk_id=chunk.id,
                    provider=embedding.name,
                    model=embedding.model,
                    dimensions=embedding.dimensions,
                    embedding=vector,
                )
            )
        await session.commit()
        service = ControlledGroundedDraftService(
            session,
            provider=MockAIProvider(),
            settings=_settings().model_copy(update={"document_retrieval_top_k": 1}),
            now=lambda: NOW + timedelta(minutes=1),
        )
        prepared = await service.prepare(
            authenticated_user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            canvas_id=node.canvas_id,
            selected_node_ids=[node.id],
            instruction="What exact evidence was selected?",
            idempotency_key="current-version-top-k",
            correlation_id="current-version-top-k",
        )
        await session.commit()
        result = await service.execute(
            authenticated_user_id=bundle.execution.user_id, request=prepared.request
        )
        assert result.insufficient_evidence is False
        assert [citation.chunk_id for citation in result.citations] == [current_chunk.id]
        assert result.citations[0].document_version == 2


async def test_rejected_document_text_cannot_enter_provider_through_notes(
    database: Database,
) -> None:
    bundle, _, node, version, chunk = await _seed_selected_context(database)
    rejected_text = "UNADMITTED_DOCUMENT_SENTINEL botanical orchids fertilizer horticulture."
    provider = _RecordingGroundedProvider()
    async with database.sessions() as session:
        stored_node = await session.get(CanvasNode, node.id)
        assert stored_node is not None
        stored_node.type, stored_node.text = "document", ""
        rejected_document = Document(
            id=uuid.uuid4(),
            canvas_id=node.canvas_id,
            file_name="unrelated.txt",
            file_type="txt",
            media_type="text/plain",
            file_size_bytes=len(rejected_text),
            content_sha256="3" * 64,
            status="ready",
            processing_stage="ready",
            chunk_count=1,
            extracted_text=rejected_text,
        )
        rejected_version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=rejected_document.id,
            version=1,
            file_name="unrelated.txt",
            file_type="txt",
            media_type="text/plain",
            file_size_bytes=len(rejected_text),
            content_sha256="3" * 64,
            storage_key=f"test/{uuid.uuid4()}.txt",
            extracted_text=rejected_text,
            status="ready",
        )
        rejected_node = CanvasNode(
            id=uuid.uuid4(),
            canvas_id=node.canvas_id,
            type="document",
            title="Rejected document",
            text="",
            position_x=0,
            position_y=0,
        )
        note = CanvasNode(
            id=uuid.uuid4(),
            canvas_id=node.canvas_id,
            type="note",
            title="Review note",
            text="Operator review note",
            position_x=0,
            position_y=0,
        )
        rejected_chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=rejected_document.id,
            document_version=1,
            chunk_index=0,
            content=rejected_text,
            char_start=0,
            char_end=len(rejected_text),
        )
        session.add_all([rejected_document, rejected_version, rejected_node, rejected_chunk, note])
        await session.flush()
        for selected_node, document_id in [
            (stored_node, version.document_id),
            (rejected_node, rejected_document.id),
        ]:
            session.add(
                CanvasDocumentNode(
                    node_id=selected_node.id, canvas_id=node.canvas_id, document_id=document_id
                )
            )
        embedding = MockEmbeddingProvider()
        for selected_chunk in [chunk, rejected_chunk]:
            session.add(
                DocumentEmbedding(
                    document_id=selected_chunk.document_id,
                    chunk_id=selected_chunk.id,
                    provider=embedding.name,
                    model=embedding.model,
                    dimensions=embedding.dimensions,
                    embedding=(await embedding.embed([selected_chunk.content]))[0],
                )
            )
        await session.commit()
        service = ControlledGroundedDraftService(
            session,
            provider=provider,
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        )
        prepared = await service.prepare(
            authenticated_user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            canvas_id=node.canvas_id,
            selected_node_ids=[node.id, rejected_node.id, note.id],
            instruction="What exact evidence was selected?",
            idempotency_key="document-note-admission",
            correlation_id="document-note-admission",
        )
        await session.commit()
        result = await service.execute(
            authenticated_user_id=bundle.execution.user_id, request=prepared.request
        )
        assert result.insufficient_evidence is False
        assert provider.sources_seen is not None and provider.notes_seen is not None
        assert {source.document_id for source in provider.sources_seen} == {version.document_id}
        assert rejected_text not in provider.notes_seen.rendered
        assert provider.notes_seen.node_ids == [note.id]
        assert "Operator review note" in provider.notes_seen.rendered


async def test_grounded_provider_receives_actual_instruction_not_client_request_id(
    database: Database,
) -> None:
    bundle, _, node, _, _ = await _seed_selected_context(database)
    instruction = "What exact evidence was selected?"
    request = request_for(
        bundle, node.canvas_id, instruction=instruction, client_request_id="tracking-only-id"
    )
    provider = _RecordingGroundedProvider()
    async with database.sessions() as session:
        service = ControlledGroundedDraftService(
            session,
            provider=provider,
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        )
        await service.execute(authenticated_user_id=bundle.execution.user_id, request=request)
        assert provider.instruction_seen == instruction
        recorded = await session.get(AIRequest, request.execution_id)
        assert recorded is not None and recorded.instruction == instruction


@pytest.mark.parametrize(
    "instruction",
    [
        "What is the orbital velocity of Neptune's moon Proteus?",
        "When did the copper mine start commercial production?",
    ],
)
async def test_prepared_document_draft_refuses_query_without_relevant_selected_chunks(
    database: Database,
    instruction: str,
) -> None:
    bundle, _, node, version, chunk = await _seed_selected_context(database)
    provider = _RecordingGroundedProvider()
    async with database.sessions() as session:
        stored_node = await session.get(CanvasNode, node.id)
        assert stored_node is not None
        stored_node.type = "document"
        stored_node.text = ""
        session.add(
            CanvasDocumentNode(
                node_id=node.id, canvas_id=node.canvas_id, document_id=version.document_id
            )
        )
        embedding = MockEmbeddingProvider()
        session.add(
            DocumentEmbedding(
                document_id=version.document_id,
                chunk_id=chunk.id,
                provider=embedding.name,
                model=embedding.model,
                dimensions=embedding.dimensions,
                embedding=(await embedding.embed([chunk.content]))[0],
            )
        )
        await session.commit()
        service = ControlledGroundedDraftService(
            session,
            provider=provider,
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        )
        prepared = await service.prepare(
            authenticated_user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            canvas_id=node.canvas_id,
            selected_node_ids=[node.id],
            instruction=instruction,
            idempotency_key="unsupported-document-question",
            correlation_id="unsupported-question-test",
        )
        await session.commit()
        result = await service.execute(
            authenticated_user_id=bundle.execution.user_id, request=prepared.request
        )
        assert result.insufficient_evidence is True
        assert result.citations == ()
        assert "lack sufficient evidence" in result.text
        assert provider.instruction_seen is None


@pytest.mark.parametrize("change", ["deleted", "replacement_version"])
async def test_prepared_document_card_rejects_deleted_or_replaced_evidence(
    database: Database,
    change: str,
) -> None:
    bundle, _, node, version, _ = await _seed_selected_context(database)
    async with database.sessions() as session:
        stored_node = await session.get(CanvasNode, node.id)
        assert stored_node is not None
        stored_node.type = "document"
        stored_node.text = ""
        session.add(
            CanvasDocumentNode(
                node_id=node.id, canvas_id=node.canvas_id, document_id=version.document_id
            )
        )
        await session.commit()
        service = ControlledGroundedDraftService(
            session,
            provider=MockAIProvider(),
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        )
        prepared = await service.prepare(
            authenticated_user_id=bundle.execution.user_id,
            workspace_id=bundle.execution.workspace_id,
            canvas_id=node.canvas_id,
            selected_node_ids=[node.id],
            instruction="What exact evidence was selected?",
            idempotency_key="document-card-stale",
            correlation_id="document-card-stale-regression",
        )
        await session.commit()
        document = await session.get(Document, version.document_id)
        assert document is not None
        if change == "deleted":
            document.deleted_at = NOW + timedelta(seconds=30)
        else:
            document.current_version = 2
            session.add(
                DocumentVersion(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    version=2,
                    file_name=version.file_name,
                    file_type=version.file_type,
                    media_type=version.media_type,
                    file_size_bytes=version.file_size_bytes,
                    content_sha256="2" * 64,
                    storage_key=f"test/{uuid.uuid4()}.txt",
                    extracted_text=version.extracted_text,
                    status="ready",
                )
            )
        await session.commit()
        with pytest.raises(ControlledDraftError) as raised:
            await service.execute(
                authenticated_user_id=bundle.execution.user_id, request=prepared.request
            )
        assert raised.value.code == "immutable_context_unavailable"
        assert await session.scalar(select(func.count()).select_from(AIResponse)) == 0


async def test_controlled_draft_persists_immutable_evidence_trace_and_usage(
    database: Database,
) -> None:
    bundle, _, node, _, chunk = await _seed_selected_context(database)
    request = request_for(
        bundle,
        node.canvas_id,
        instruction="What exact evidence was selected?",
        idempotency_key="terra:grounded-draft:one",
    )
    async with database.sessions() as session:
        result = await ControlledGroundedDraftService(
            session,
            provider=MockAIProvider(),
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        ).execute(authenticated_user_id=bundle.execution.user_id, request=request)
        assert result.execution_id == bundle.execution.execution_id
        assert result.insufficient_evidence is False
        assert len(result.citations) == 1
        assert result.citations[0].chunk_id == chunk.id
        assert result.citations[0].quote == "Exact selected chunk evidence"

    async with database.sessions() as session:
        request_row = await session.get(AIRequest, bundle.execution.execution_id)
        response = await session.scalar(
            select(AIResponse).where(AIResponse.request_id == bundle.execution.execution_id)
        )
        citation = await session.scalar(select(Citation).where(Citation.chunk_id == chunk.id))
        execution_citation = await session.scalar(
            select(AIExecutionCitation).where(
                AIExecutionCitation.request_id == bundle.execution.execution_id
            )
        )
        claim = await session.scalar(
            select(AIClaim).where(AIClaim.request_id == bundle.execution.execution_id)
        )
        usage = await session.scalar(
            select(UsageRecord).where(UsageRecord.operation == "controlled_agent_draft")
        )
        states = tuple(
            (
                await session.scalars(
                    select(ControlledAgentExecutionState)
                    .join(
                        ControlledAgentStateTransition,
                        ControlledAgentStateTransition.state_id
                        == ControlledAgentExecutionState.state_id,
                    )
                    .where(
                        ControlledAgentExecutionState.execution_id == bundle.execution.execution_id
                    )
                    .order_by(ControlledAgentStateTransition.sequence)
                )
            ).all()
        )
    assert request_row is not None and request_row.status == "completed"
    assert request_row.context_snapshot[0]["resourceKind"] == "node"
    assert response is not None and response.grounded is True
    assert citation is not None and citation.document_version == 1
    assert (
        execution_citation is not None and execution_citation.ai_response_id_snapshot == response.id
    )
    assert claim is not None and claim.evidence_status == "supported"
    assert usage is not None and usage.metadata_payload["executionId"] == str(
        bundle.execution.execution_id
    )
    assert [row.status for row in states] == ["proposed", "ready", "running", "succeeded"]


class _FailingProvider:
    name = "openai"
    model = "failing-test-model"
    configuration_version = "test-provider-v1"
    mock = False

    async def generate(self, instruction: str, context: ContextBundle) -> None:
        raise AIProviderError("unexpected")

    async def generate_grounded(
        self, instruction: str, notes_context: ContextBundle, sources: list[GroundedSource]
    ) -> GroundedAIResult:
        raise AIProviderError("provider unavailable")


async def test_provider_failure_records_safe_failure_without_response(database: Database) -> None:
    bundle, _, node, _, _ = await _seed_selected_context(database)
    request = request_for(
        bundle,
        node.canvas_id,
        idempotency_key="terra:provider-failure:one",
    )
    async with database.sessions() as session:
        service = ControlledGroundedDraftService(
            session,
            provider=_FailingProvider(),  # type: ignore[arg-type]
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        )
        with pytest.raises(ControlledDraftError, match="configured reasoning provider") as exc:
            await service.execute(authenticated_user_id=bundle.execution.user_id, request=request)
        assert exc.value.code == "provider_failure"

    async with database.sessions() as session:
        request_row = await session.get(AIRequest, bundle.execution.execution_id)
        response_count = await session.scalar(select(func.count()).select_from(AIResponse))
    assert request_row is not None
    assert request_row.status == "failed"
    assert request_row.safe_error_category == "provider_failure"
    assert response_count == 0


class _CancellingProvider:
    name = "mock"
    model = "cancelling-test-model"
    configuration_version = "test-provider-v1"
    mock = True

    def __init__(
        self,
        database: Database,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> None:
        self.database = database
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.execution_id = execution_id

    async def generate(self, instruction: str, context: ContextBundle) -> None:
        raise AssertionError("not used")

    async def generate_grounded(
        self, instruction: str, notes_context: ContextBundle, sources: list[GroundedSource]
    ) -> GroundedAIResult:
        async with self.database.sessions() as session:
            await ControlledExecutionLifecycle(session).cancel(
                authenticated_user_id=self.user_id,
                request=CancellationRequest(
                    cancellation_id=uuid.uuid4(),
                    execution_id=self.execution_id,
                    user_id=self.user_id,
                    workspace_id=self.workspace_id,
                    requested_at=NOW + timedelta(minutes=1, seconds=1),
                ),
                trace_id=uuid.uuid4(),
            )
            await session.commit()
        return GroundedAIResult(
            text="Late draft",
            insufficient_evidence=False,
            citations=[GroundedCitation(source_id=sources[0].source_id, claim="Late draft")],
            general_analysis=None,
            provider_response_id=None,
        )


async def test_cancelled_execution_suppresses_late_provider_result(database: Database) -> None:
    bundle, _, node, _, _ = await _seed_selected_context(database)
    request = request_for(
        bundle,
        node.canvas_id,
        idempotency_key="terra:cancelled-result:one",
    )
    provider = _CancellingProvider(
        database,
        user_id=bundle.execution.user_id,
        workspace_id=bundle.execution.workspace_id,
        execution_id=bundle.execution.execution_id,
    )
    async with database.sessions() as session:
        service = ControlledGroundedDraftService(
            session,
            provider=provider,  # type: ignore[arg-type]
            settings=_settings(),
            now=lambda: NOW + timedelta(minutes=1),
        )
        with pytest.raises(ControlledDraftError, match="not accepted") as exc:
            await service.execute(authenticated_user_id=bundle.execution.user_id, request=request)
        assert exc.value.code == "result_not_accepted"

    async with database.sessions() as session:
        request_row = await session.get(AIRequest, bundle.execution.execution_id)
        response_count = await session.scalar(select(func.count()).select_from(AIResponse))
    assert request_row is not None and request_row.status == "failed"
    assert request_row.safe_error_category in {"stale_execution_state", "execution_cancelled"}
    assert response_count == 0
