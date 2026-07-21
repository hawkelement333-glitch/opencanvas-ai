from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, NoReturn, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.api.dependencies import get_ai_provider
from opencanvas_api.api.routes import documents as document_routes
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    AIExecutionChunk,
    AIExecutionCitation,
    AIExecutionNode,
    AIExecutionSource,
    AIRequest,
    AIResponse,
    AIResponseSource,
    CanvasDocumentNode,
    Citation,
    Document,
    DocumentChunk,
    DocumentEmbedding,
    DocumentFile,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.ai import GroundedAIResult, GroundedCitation, GroundedSource
from opencanvas_api.services.context import ContextBundle
from opencanvas_api.services.documents import DocumentStorageError
from tests.document_fixtures import make_pdf_bytes
from tests.test_canvas_api import _create_canvas, _create_node

JsonObject = dict[str, Any]


async def _upload(
    client: httpx.AsyncClient,
    prefix: str,
    canvas_id: str,
    *,
    filename: str,
    content: bytes,
    media_type: str,
    x: float = 80,
) -> httpx.Response:
    return await client.post(
        f"{prefix}/canvases/{canvas_id}/documents",
        files={"file": (filename, content, media_type)},
        data={"x": str(x), "y": "120"},
    )


async def test_complete_upload_process_select_query_cite_trace_and_delete_workflow(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Grounded research")
    note = await _create_node(
        client,
        api_prefix,
        canvas["id"],
        title="Review goal",
        text="Verify the observatory calibration record.",
    )
    pdf_bytes = make_pdf_bytes(
        "The observatory calibration code is NOVA-731. The verified aperture is 6.5 meters."
    )
    pdf_response = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="observatory-facts.pdf",
        content=pdf_bytes,
        media_type="application/pdf",
        x=420,
    )
    assert pdf_response.status_code == 201, pdf_response.text
    pdf_upload = cast(JsonObject, pdf_response.json())
    assert pdf_upload["document"]["status"] == "queued"
    assert pdf_upload["document"]["processingStage"] == "queued"
    assert pdf_upload["document"]["pageCount"] is None
    assert pdf_upload["node"]["type"] == "document"
    assert pdf_upload["node"]["document"]["id"] == pdf_upload["document"]["id"]
    metadata = await client.get(f"{api_prefix}/documents/{pdf_upload['document']['id']}")
    assert metadata.status_code == 200
    assert metadata.json()["fileName"] == "observatory-facts.pdf"
    assert metadata.json()["status"] == "ready"
    assert metadata.json()["processingStage"] == "ready"
    assert metadata.json()["pageCount"] == 1
    extracted = await client.get(f"{api_prefix}/documents/{pdf_upload['document']['id']}/text")
    assert extracted.status_code == 200
    assert "NOVA-731" in extracted.json()["text"]
    assert extracted.json()["sections"][0]["pageNumber"] == 1

    distractor = (
        b"# Garden notes\n\nTomato seedlings require gentle watering and warm soil.\n\n"
        b"## Kitchen inventory\n\nThe pantry contains lentils, cinnamon, and rice."
    )
    distractor_response = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="unrelated.md",
        content=distractor,
        media_type="text/markdown",
        x=820,
    )
    assert distractor_response.status_code == 201, distractor_response.text
    distractor_upload = cast(JsonObject, distractor_response.json())

    duplicate_response = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{pdf_upload['node']['id']}/duplicate",
        json={"revision": pdf_upload["node"]["revision"]},
    )
    assert duplicate_response.status_code == 201
    duplicate = cast(JsonObject, duplicate_response.json())
    assert duplicate["document"]["id"] == pdf_upload["document"]["id"]

    generic_delete = await client.delete(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{duplicate['id']}",
        params={"revision": duplicate["revision"]},
    )
    assert generic_delete.status_code == 409
    assert generic_delete.json()["code"] == "document_delete_required"

    search = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/documents/search",
        json={
            "query": "What is the observatory calibration code NOVA-731?",
            "documentIds": [
                pdf_upload["document"]["id"],
                distractor_upload["document"]["id"],
            ],
            "topK": 4,
            "minRelevance": 0.2,
        },
    )
    assert search.status_code == 200, search.text
    search_result = cast(JsonObject, search.json())
    assert search_result["insufficientContext"] is False
    assert search_result["matches"]
    assert all(
        match["documentId"] in {pdf_upload["document"]["id"], distractor_upload["document"]["id"]}
        for match in search_result["matches"]
    )

    instruction = "What is the observatory calibration code NOVA-731?"
    grounded_response = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": instruction,
            "selectedNodeIds": [
                note["id"],
                pdf_upload["node"]["id"],
                distractor_upload["node"]["id"],
            ],
        },
    )
    assert grounded_response.status_code == 201, grounded_response.text
    grounded = cast(JsonObject, grounded_response.json())
    assert grounded["grounded"] is True
    assert grounded["insufficientEvidence"] is False
    assert grounded["citations"]
    citation = grounded["citations"][0]
    assert citation["documentTitle"] == "observatory-facts.pdf"
    assert citation["pageNumber"] == 1
    assert citation["sourceId"].startswith("chunk_")
    assert "NOVA-731" in citation["excerpt"]
    assert grounded["node"]["citations"] == grounded["citations"]
    assert any(
        edge["kind"] == "cites"
        and edge["sourceNodeId"] == grounded["node"]["id"]
        and edge["targetNodeId"] == pdf_upload["node"]["id"]
        for edge in grounded["edges"]
    )

    passage = await client.get(
        f"{api_prefix}/documents/{citation['documentId']}/chunks/{citation['chunkId']}"
    )
    assert passage.status_code == 200
    assert passage.json()["text"] == citation["excerpt"]

    restored = await client.get(f"{api_prefix}/canvases/{canvas['id']}/snapshot")
    restored_ai = next(
        node for node in restored.json()["nodes"] if node["id"] == grounded["node"]["id"]
    )
    assert restored_ai["citations"] == grounded["citations"]

    request_id = uuid.UUID(cast(str, grounded["requestId"]))
    async with database.sessions() as session:
        request = await session.get(AIRequest, request_id)
        execution_nodes = (
            await session.scalars(
                select(AIExecutionNode)
                .where(AIExecutionNode.request_id == request_id)
                .order_by(AIExecutionNode.selected_order)
            )
        ).all()
        candidate_rows = (
            await session.scalars(
                select(AIExecutionChunk)
                .where(AIExecutionChunk.request_id == request_id)
                .order_by(AIExecutionChunk.rank)
            )
        ).all()
        ai_response = await session.scalar(
            select(AIResponse).where(AIResponse.request_id == request_id)
        )
        stored_file = await session.scalar(
            select(DocumentFile).where(
                DocumentFile.document_id == uuid.UUID(pdf_upload["document"]["id"])
            )
        )
    assert request is not None
    assert request.instruction == instruction
    assert request.prompt_version == "grounded-block-citations-v1"
    assert "systemInstructions" not in request.model_configuration
    assert request.model_configuration["providerConfigurationVersion"]
    assert request.model_configuration["maxOutputTokens"] == 1_600
    assert request.retrieval_configuration["selectedDocumentIds"] == [
        pdf_upload["document"]["id"],
        distractor_upload["document"]["id"],
    ]
    assert [row.node_id for row in execution_nodes] == [
        uuid.UUID(note["id"]),
        uuid.UUID(pdf_upload["node"]["id"]),
        uuid.UUID(distractor_upload["node"]["id"]),
    ]
    assert execution_nodes[0].content_snapshot == note["text"]
    pdf_snapshot = json.loads(execution_nodes[1].content_snapshot)
    assert pdf_snapshot["fileName"] == "observatory-facts.pdf"
    assert len(pdf_snapshot["contentSha256"]) == 64
    assert candidate_rows
    assert any(row.included_in_context for row in candidate_rows)
    assert any(not row.included_in_context for row in candidate_rows)
    assert all(row.source_id_snapshot.startswith("chunk_") for row in candidate_rows)
    assert ai_response is not None and ai_response.grounded is True
    assert ai_response.input_tokens is None
    assert stored_file is not None
    stored_path = tmp_path / "documents" / Path(stored_file.storage_key)
    assert stored_path.is_file()

    unsupported_question = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": "What is the orbital velocity of Neptune's moon Proteus?",
            "selectedNodeIds": [pdf_upload["node"]["id"]],
        },
    )
    assert unsupported_question.status_code == 201
    insufficient = unsupported_question.json()
    assert insufficient["grounded"] is False
    assert insufficient["insufficientEvidence"] is True
    assert insufficient["citations"] == []
    assert "lack sufficient evidence" in insufficient["node"]["text"]

    deleted = await client.delete(f"{api_prefix}/documents/{pdf_upload['document']['id']}")
    assert deleted.status_code == 204, deleted.text
    assert not stored_path.exists()
    async with database.sessions() as session:
        document_count = await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.id == uuid.UUID(pdf_upload["document"]["id"]))
        )
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == uuid.UUID(pdf_upload["document"]["id"]))
        )
        embedding_count = await session.scalar(
            select(func.count())
            .select_from(DocumentEmbedding)
            .where(DocumentEmbedding.document_id == uuid.UUID(pdf_upload["document"]["id"]))
        )
        reference_count = await session.scalar(
            select(func.count())
            .select_from(CanvasDocumentNode)
            .where(CanvasDocumentNode.document_id == uuid.UUID(pdf_upload["document"]["id"]))
        )
        citation_count = await session.scalar(
            select(func.count())
            .select_from(Citation)
            .where(Citation.document_id == uuid.UUID(pdf_upload["document"]["id"]))
        )
        source_count = await session.scalar(
            select(func.count())
            .select_from(AIResponseSource)
            .where(AIResponseSource.document_id == uuid.UUID(pdf_upload["document"]["id"]))
        )
    assert (document_count, chunk_count, embedding_count) == (0, 0, 0)
    assert (reference_count, citation_count, source_count) == (0, 0, 0)


@pytest.mark.security
async def test_upload_endpoint_rejects_unsupported_malformed_oversized_and_empty_files(
    client: httpx.AsyncClient,
    app: FastAPI,
    api_prefix: str,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Secure uploads")

    unsupported = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="payload.exe",
        content=b"MZ executable",
        media_type="application/octet-stream",
    )
    assert unsupported.status_code == 415

    malformed = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="fake.pdf",
        content=b"not a pdf",
        media_type="application/pdf",
    )
    assert malformed.status_code == 422

    empty = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="empty.txt",
        content=b"",
        media_type="text/plain",
    )
    assert empty.status_code == 422

    current_settings = cast(Settings, app.dependency_overrides[get_settings]())
    small_limit = current_settings.model_copy(update={"document_max_file_size_bytes": 1_024})
    app.dependency_overrides[get_settings] = lambda: small_limit
    oversized = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="large.txt",
        content=b"x" * 1_025,
        media_type="text/plain",
    )
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "file_too_large"


@pytest.mark.security
async def test_upload_sanitizes_filename_and_failed_processing_can_retry(
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Processing failures")
    sanitized = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="../../safe-fact.md",
        content=b"# Fact\n\nThe answer is forty-two.",
        media_type="text/markdown",
    )
    assert sanitized.status_code == 201
    assert sanitized.json()["document"]["fileName"] == "safe-fact.md"

    image_only = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="scan.pdf",
        content=make_pdf_bytes(""),
        media_type="application/pdf",
        x=400,
    )
    assert image_only.status_code == 201
    queued = image_only.json()["document"]
    assert queued["status"] == "queued"
    assert queued["processingStage"] == "queued"
    failed_response = await client.get(f"{api_prefix}/documents/{queued['id']}")
    failed = failed_response.json()
    assert failed["status"] == "failed"
    assert failed["processingStage"] == "failed"
    assert "OCR" in failed["errorMessage"]

    retried = await client.post(f"{api_prefix}/documents/{failed['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["processingStage"] == "retrying"
    retried_status = await client.get(f"{api_prefix}/documents/{failed['id']}")
    assert retried_status.json()["status"] == "failed"
    assert "OCR" in retried_status.json()["errorMessage"]


class InvalidCitationProvider:
    name = "openai"
    model = "test-grounded-model"
    mock = False

    async def generate(self, instruction: str, context: ContextBundle) -> NoReturn:
        raise AssertionError("The note-only path should not be used.")

    async def generate_grounded(
        self,
        instruction: str,
        notes_context: ContextBundle,
        sources: list[GroundedSource],
    ) -> GroundedAIResult:
        return GroundedAIResult(
            text="A fabricated grounded answer.",
            insufficient_evidence=False,
            citations=[GroundedCitation(source_id="chunk_forged", claim="Fabricated claim")],
            general_analysis=None,
            provider_response_id="unsafe-response",
        )


_LONG_CLAIM_A = "A" * 3_000
_LONG_CLAIM_B = "B" * 3_000


class RepeatedCitationProvider:
    name = "openai"
    model = "test-grounded-model"
    mock = False

    async def generate(self, instruction: str, context: ContextBundle) -> NoReturn:
        raise AssertionError("The note-only path should not be used.")

    async def generate_grounded(
        self,
        instruction: str,
        notes_context: ContextBundle,
        sources: list[GroundedSource],
    ) -> GroundedAIResult:
        source_id = sources[0].source_id
        return GroundedAIResult(
            text="The calibration code is NOVA-731 and it is verified.",
            insufficient_evidence=False,
            citations=[
                GroundedCitation(source_id=source_id, claim=_LONG_CLAIM_A),
                GroundedCitation(source_id=source_id, claim=_LONG_CLAIM_B),
            ],
            general_analysis=None,
            provider_response_id="repeated-citation-response",
        )


class SnapshotCaptureProvider:
    name = "mock"
    model = "snapshot-capture-v1"
    mock = True
    configuration_version = "snapshot-capture-v1"

    def __init__(self) -> None:
        self.calls: list[list[GroundedSource]] = []

    async def generate(self, instruction: str, context: ContextBundle) -> NoReturn:
        raise AssertionError("The note-only path should not be used.")

    async def generate_grounded(
        self,
        instruction: str,
        notes_context: ContextBundle,
        sources: list[GroundedSource],
    ) -> GroundedAIResult:
        del instruction, notes_context
        self.calls.append(sources)
        source = sources[0]
        return GroundedAIResult(
            text=f"Snapshot evidence: {source.text}",
            insufficient_evidence=False,
            citations=[GroundedCitation(source_id=source.source_id, claim=source.text)],
            general_analysis=None,
            provider_response_id=f"snapshot-{len(self.calls)}",
        )


async def test_reruns_preserve_original_document_version_and_resolve_current_version(
    client: httpx.AsyncClient,
    app: FastAPI,
    api_prefix: str,
    database: Database,
) -> None:
    provider = SnapshotCaptureProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    canvas = await _create_canvas(client, api_prefix, "Versioned reruns")
    uploaded = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="versioned.md",
        content=b"# Launch code\n\nThe immutable launch code is ALPHA-101.",
        media_type="text/markdown",
    )
    assert uploaded.status_code == 201, uploaded.text
    upload = uploaded.json()
    initial = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": "What is the immutable launch code?",
            "selectedNodeIds": [upload["node"]["id"]],
        },
    )
    assert initial.status_code == 201, initial.text
    initial_result = initial.json()
    assert provider.calls[0][0].document_version == 1
    assert "ALPHA-101" in provider.calls[0][0].text

    replaced = await client.post(
        f"{api_prefix}/documents/{upload['document']['id']}/replace",
        files={
            "file": (
                "versioned.md",
                b"# Launch code\n\nThe current launch code is BETA-202.",
                "text/markdown",
            )
        },
    )
    assert replaced.status_code == 200, replaced.text
    ready = await client.get(f"{api_prefix}/documents/{upload['document']['id']}")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    original_rerun = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai/{initial_result['requestId']}/rerun-original"
    )
    current_rerun = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai/{initial_result['requestId']}/rerun-current"
    )
    assert original_rerun.status_code == 201, original_rerun.text
    assert current_rerun.status_code == 201, current_rerun.text
    assert provider.calls[1][0].document_version == 1
    assert "ALPHA-101" in provider.calls[1][0].text
    assert "BETA-202" not in provider.calls[1][0].text
    assert provider.calls[2][0].document_version == 2
    assert "BETA-202" in provider.calls[2][0].text
    assert (
        original_rerun.json()["citations"][0]["chunkId"]
        == initial_result["citations"][0]["chunkId"]
    )
    assert original_rerun.json()["citations"][0]["documentId"] == upload["document"]["id"]

    async with database.sessions() as session:
        initial_chunks = list(
            (
                await session.scalars(
                    select(AIExecutionChunk)
                    .where(AIExecutionChunk.request_id == uuid.UUID(initial_result["requestId"]))
                    .order_by(AIExecutionChunk.rank)
                )
            ).all()
        )
        original_chunks = list(
            (
                await session.scalars(
                    select(AIExecutionChunk)
                    .where(
                        AIExecutionChunk.request_id == uuid.UUID(original_rerun.json()["requestId"])
                    )
                    .order_by(AIExecutionChunk.rank)
                )
            ).all()
        )
        current_chunks = list(
            (
                await session.scalars(
                    select(AIExecutionChunk)
                    .where(
                        AIExecutionChunk.request_id == uuid.UUID(current_rerun.json()["requestId"])
                    )
                    .order_by(AIExecutionChunk.rank)
                )
            ).all()
        )
    assert [row.chunk_id_snapshot for row in original_chunks] == [
        row.chunk_id_snapshot for row in initial_chunks
    ]
    assert {row.document_version_snapshot for row in original_chunks} == {1}
    assert {row.document_version_snapshot for row in current_chunks} == {2}


@pytest.mark.security
async def test_invalid_model_citation_is_rejected_without_partial_response(
    client: httpx.AsyncClient,
    app: FastAPI,
    api_prefix: str,
    database: Database,
) -> None:
    app.dependency_overrides[get_ai_provider] = lambda: InvalidCitationProvider()
    canvas = await _create_canvas(client, api_prefix, "Citation boundary")
    uploaded = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="fact.md",
        content=b"# Verified fact\n\nThe calibration code is NOVA-731.",
        media_type="text/markdown",
    )
    assert uploaded.status_code == 201
    node_id = uploaded.json()["node"]["id"]

    response = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": "What is the calibration code?",
            "selectedNodeIds": [node_id],
        },
    )

    assert response.status_code == 502
    assert response.json()["code"] == "ai_provider_error"
    async with database.sessions() as session:
        requests = (await session.scalars(select(AIRequest))).all()
        response_count = await session.scalar(select(func.count()).select_from(AIResponse))
    assert len(requests) == 1
    assert requests[0].status == "failed"
    assert "not retrieved" in cast(str, requests[0].error)
    assert response_count == 0


async def test_deleting_canvas_removes_opaque_document_file(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Disposable workspace")
    uploaded = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="temporary.txt",
        content=b"A temporary but searchable source record.",
        media_type="text/plain",
    )
    assert uploaded.status_code == 201
    document_id = uuid.UUID(uploaded.json()["document"]["id"])
    async with database.sessions() as session:
        stored_file = await session.scalar(
            select(DocumentFile).where(DocumentFile.document_id == document_id)
        )
    assert stored_file is not None
    stored_path = tmp_path / "documents" / Path(stored_file.storage_key)
    assert stored_path.is_file()

    current_canvas = await client.get(f"{api_prefix}/canvases/{canvas['id']}")
    deleted = await client.delete(
        f"{api_prefix}/canvases/{canvas['id']}",
        params={"revision": current_canvas.json()["revision"]},
    )

    assert deleted.status_code == 204
    assert not stored_path.exists()
    async with database.sessions() as session:
        assert await session.get(Document, document_id) is None


async def test_document_delete_rolls_back_when_physical_storage_delete_fails(
    client: httpx.AsyncClient,
    api_prefix: str,
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = await _create_canvas(client, api_prefix, "Storage rollback")
    uploaded = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="retryable-delete.txt",
        content=b"This stored source must remain retryable after an unlink failure.",
        media_type="text/plain",
    )
    assert uploaded.status_code == 201
    document_id = uuid.UUID(uploaded.json()["document"]["id"])
    async with database.sessions() as session:
        stored_file = await session.scalar(
            select(DocumentFile).where(DocumentFile.document_id == document_id)
        )
    assert stored_file is not None
    stored_path = tmp_path / "documents" / Path(stored_file.storage_key)
    assert stored_path.is_file()

    original_builder = document_routes.build_document_storage

    class FailingDeleteStorage:
        async def delete(self, storage_key: str) -> None:
            del storage_key
            raise DocumentStorageError("The stored document could not be removed.")

    monkeypatch.setattr(
        document_routes,
        "build_document_storage",
        lambda settings: FailingDeleteStorage(),
    )
    failed = await client.delete(f"{api_prefix}/documents/{document_id}")

    assert failed.status_code == 500
    assert failed.json()["code"] == "storage_failed"
    assert stored_path.is_file()
    async with database.sessions() as session:
        assert await session.get(Document, document_id) is not None
        assert (
            await session.scalar(
                select(DocumentFile.id).where(DocumentFile.document_id == document_id)
            )
            is not None
        )

    monkeypatch.setattr(document_routes, "build_document_storage", original_builder)
    retried = await client.delete(f"{api_prefix}/documents/{document_id}")
    assert retried.status_code == 204
    assert not stored_path.exists()


async def test_immutable_citation_audit_survives_source_and_response_node_deletion(
    client: httpx.AsyncClient,
    app: FastAPI,
    api_prefix: str,
    database: Database,
) -> None:
    app.dependency_overrides[get_ai_provider] = lambda: RepeatedCitationProvider()
    canvas = await _create_canvas(client, api_prefix, "Durable audit")
    uploaded = await _upload(
        client,
        api_prefix,
        canvas["id"],
        filename="verified.md",
        content=b"# Verified code\n\nThe calibration code is NOVA-731 and it is verified.",
        media_type="text/markdown",
    )
    assert uploaded.status_code == 201
    upload = uploaded.json()

    answer = await client.post(
        f"{api_prefix}/canvases/{canvas['id']}/ai",
        json={
            "instruction": "What is the verified calibration code?",
            "selectedNodeIds": [upload["node"]["id"]],
        },
    )
    assert answer.status_code == 201, answer.text
    result = answer.json()
    request_id = uuid.UUID(result["requestId"])
    response_id = uuid.UUID(result["responseId"])
    response_node_id = uuid.UUID(result["node"]["id"])
    document_id = uuid.UUID(upload["document"]["id"])
    document_node_id = uuid.UUID(upload["node"]["id"])
    assert len(result["citations"]) == 1  # Live display citations are source-deduplicated.
    assert len(result["citations"][0]["claim"]) == 4_000
    assert result["citations"][0]["claim"].startswith(_LONG_CLAIM_A)

    original_response_content = result["node"]["text"]
    edited = await client.patch(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{response_node_id}",
        json={
            "revision": result["node"]["revision"],
            "text": "A user-edited answer that is no longer represented as source-grounded.",
        },
    )
    assert edited.status_code == 200, edited.text
    edited_node = edited.json()
    restored = await client.get(f"{api_prefix}/canvases/{canvas['id']}/snapshot")
    assert restored.status_code == 200
    restored_answer = next(
        node for node in restored.json()["nodes"] if node["id"] == str(response_node_id)
    )
    assert restored_answer["citations"] == []
    assert not any(
        edge["kind"] == "cites" and edge["sourceNodeId"] == str(response_node_id)
        for edge in restored.json()["edges"]
    )

    deleted_source = await client.delete(f"{api_prefix}/documents/{document_id}")
    assert deleted_source.status_code == 204
    deleted_response_node = await client.delete(
        f"{api_prefix}/canvases/{canvas['id']}/nodes/{response_node_id}",
        params={"revision": edited_node["revision"]},
    )
    assert deleted_response_node.status_code == 204

    async with database.sessions() as session:
        execution_citations = (
            await session.scalars(
                select(AIExecutionCitation)
                .where(AIExecutionCitation.request_id == request_id)
                .order_by(AIExecutionCitation.ordinal)
            )
        ).all()
        execution_sources = (
            await session.scalars(
                select(AIExecutionSource).where(AIExecutionSource.request_id == request_id)
            )
        ).all()
        live_citation_count = await session.scalar(
            select(func.count()).select_from(Citation).where(Citation.ai_response_id == response_id)
        )
        live_source_count = await session.scalar(
            select(func.count())
            .select_from(AIResponseSource)
            .where(AIResponseSource.ai_response_id == response_id)
        )
        response = await session.get(AIResponse, response_id)

    assert [citation.ordinal for citation in execution_citations] == [1, 2]
    assert [citation.claim_snapshot for citation in execution_citations] == [
        _LONG_CLAIM_A,
        _LONG_CLAIM_B,
    ]
    assert execution_citations[0].source_id_snapshot == execution_citations[1].source_id_snapshot
    assert all(citation.document_id_snapshot == document_id for citation in execution_citations)
    assert all(citation.document_name_snapshot == "verified.md" for citation in execution_citations)
    assert execution_sources[0].response_node_id_snapshot == response_node_id
    assert execution_sources[0].document_id_snapshot == document_id
    assert execution_sources[0].document_node_id_snapshot == document_node_id
    assert execution_sources[0].document_name_snapshot == "verified.md"
    assert live_citation_count == 0
    assert live_source_count == 0
    assert response is not None and response.node_id is None
    assert response.grounded is False
    assert response.content == original_response_content
