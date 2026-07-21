from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    AIExecutionChunk,
    AIExecutionCitation,
    AIExecutionNode,
    AIExecutionSource,
    AIRequest,
    AIResponse,
    AIResponseSource,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalExecution,
    CanonicalNote,
    CanonicalObject,
    CanonicalRelationship,
    Canvas,
    CanvasDocumentNode,
    CanvasNode,
    Citation,
    Document,
    DocumentChunk,
    DocumentEmbedding,
    DocumentFile,
    DocumentProcessingJob,
    Edge,
    TraceEvent,
    User,
    Workspace,
)
from opencanvas_api.services.documents.embeddings import MockEmbeddingProvider

DEMO_CANVAS_ID = uuid.UUID("d3000000-0000-4000-8000-000000000001")
DEMO_TRACE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000002")
DEMO_REQUEST_ID = uuid.UUID("d3000000-0000-4000-8000-000000000003")
DEMO_RESPONSE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000004")
DEMO_RESPONSE_NODE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000005")
DEMO_INSUFFICIENT_REQUEST_ID = uuid.UUID("d3000000-0000-4000-8000-000000000006")
DEMO_INSUFFICIENT_RESPONSE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000007")
DEMO_INSUFFICIENT_NODE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000008")
DEMO_INSUFFICIENT_TRACE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000009")
DEMO_USER_ID = uuid.UUID("d3000000-0000-4000-8000-000000000010")
DEMO_TIMESTAMP = datetime(2026, 7, 17, 15, 0, tzinfo=UTC)

DOCUMENT_ONE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000101")
DOCUMENT_TWO_ID = uuid.UUID("d3000000-0000-4000-8000-000000000102")
DOCUMENT_ONE_NODE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000111")
DOCUMENT_TWO_NODE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000112")
NOTE_HYPOTHESIS_ID = uuid.UUID("d3000000-0000-4000-8000-000000000121")
NOTE_CONTROL_ID = uuid.UUID("d3000000-0000-4000-8000-000000000122")
CHUNK_ONE_ID = uuid.UUID("d3000000-0000-4000-8000-000000000131")
CHUNK_TWO_ID = uuid.UUID("d3000000-0000-4000-8000-000000000132")

LAUNCH_BRIEF = """# Approved pilot brief

The Project Aurora pilot is approved to launch in Chicago on October 21, 2026.
The approved launch budget is $48,000.
"""

INTERVIEW_SUMMARY = """# Research and contingency notes

Customer interviews favored a guided onboarding flow. This is qualitative evidence, not proof
that onboarding will improve adoption. A planning memo lists October 28, 2026 as a contingency
date, but it was not approved. No selected source establishes a numeric retention target.
"""

REPLAY_RESPONSE = "\n".join(
    [
        "DETERMINISTIC REPLAY — this is stored demo data, not a live model call.",
        "",
        (
            "Supported: Project Aurora is approved to launch in Chicago on October 21, 2026, "
            "with a $48,000 budget. [1]"
        ),
        "",
        (
            "Inference: Guided onboarding may improve adoption, but the selected evidence only "
            "reports a qualitative preference; it does not establish the outcome."
        ),
        "",
        (
            "Conflict: October 28 appears only as an unapproved contingency date, while October "
            "21 is the approved launch date. [1] [2]"
        ),
        "",
        "Unsupported: The selected sources do not establish a numeric retention target. [2]",
    ]
)

INSUFFICIENT_RESPONSE = "\n".join(
    [
        "DETERMINISTIC REPLAY — this is stored demo data, not a live model call.",
        "",
        "Insufficient evidence: The selected sources do not identify the project CEO's favorite ",
        "color. No grounded answer or citation can be provided.",
    ]
)


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    canvas_id: uuid.UUID
    trace_id: uuid.UUID
    created: bool


def _id(number: int) -> uuid.UUID:
    return uuid.UUID(f"d3000000-0000-4000-8000-{number:012d}")


def _timestamps() -> dict[str, datetime]:
    return {"created_at": DEMO_TIMESTAMP, "updated_at": DEMO_TIMESTAMP}


async def seed_demo(session: AsyncSession, storage_root: Path) -> DemoSeedResult:
    """Persist the deterministic replay fixture using ordinary application tables."""

    await _write_source_files(storage_root)
    if await session.get(Canvas, DEMO_CANVAS_ID) is not None:
        return DemoSeedResult(DEMO_CANVAS_ID, DEMO_TRACE_ID, created=False)

    user = User(
        id=DEMO_USER_ID,
        email="demo@mobius.invalid",
        email_normalized="demo@mobius.invalid",
        password_hash="demo-login-disabled",
        display_name="Competition demo",
        email_verified=True,
        settings_payload={"demo": True},
        **_timestamps(),
    )
    workspace = Workspace(
        id=DEMO_CANVAS_ID,
        owner_id=DEMO_USER_ID,
        name="Build Week Evidence Lab — DEMO DATA",
        description="Non-sensitive deterministic replay workspace for competition evaluation.",
        version=1,
        lifecycle_state="active",
        metadata_payload={"demo": True, "mode": "deterministic_replay"},
        legacy_canvas_id=None,
        **_timestamps(),
    )
    session.add(user)
    await session.flush()
    session.add(workspace)
    await session.flush()
    canvas = Canvas(
        id=DEMO_CANVAS_ID,
        workspace_id=DEMO_CANVAS_ID,
        name="Build Week Evidence Lab — DEMO DATA",
        viewport_x=15,
        viewport_y=20,
        viewport_zoom=0.82,
        revision=1,
        **_timestamps(),
    )
    session.add(canvas)
    await session.flush()
    workspace.legacy_canvas_id = DEMO_CANVAS_ID
    await session.flush()

    nodes = _canvas_nodes()
    session.add_all(nodes)
    await session.flush()

    documents = _documents()
    session.add_all(documents)
    await session.flush()
    session.add_all(_document_records())
    await session.flush()

    provider = MockEmbeddingProvider()
    vectors = await provider.embed([LAUNCH_BRIEF, INTERVIEW_SUMMARY])
    session.add_all(
        [
            DocumentEmbedding(
                id=_id(151),
                document_id=DOCUMENT_ONE_ID,
                chunk_id=CHUNK_ONE_ID,
                provider=provider.name,
                model=provider.model,
                dimensions=provider.dimensions,
                embedding=vectors[0],
                **_timestamps(),
            ),
            DocumentEmbedding(
                id=_id(152),
                document_id=DOCUMENT_TWO_ID,
                chunk_id=CHUNK_TWO_ID,
                provider=provider.name,
                model=provider.model,
                dimensions=provider.dimensions,
                embedding=vectors[1],
                **_timestamps(),
            ),
        ]
    )
    await session.flush()

    session.add_all(_ai_records())
    await session.flush()
    session.add_all(_ai_provenance_records())
    session.add_all(_edges())
    session.add_all(_trace_events())
    await session.flush()

    canonical_objects, canonical_details = _canonical_records()
    session.add_all(canonical_objects)
    await session.flush()
    canonical_documents = [
        detail for detail in canonical_details if isinstance(detail, CanonicalDocument)
    ]
    remaining_details = [
        detail for detail in canonical_details if not isinstance(detail, CanonicalDocument)
    ]
    session.add_all(canonical_documents)
    await session.flush()
    session.add_all(remaining_details)
    await session.commit()
    return DemoSeedResult(DEMO_CANVAS_ID, DEMO_TRACE_ID, created=True)


def _canvas_nodes() -> list[CanvasNode]:
    return [
        CanvasNode(
            id=DOCUMENT_ONE_NODE_ID,
            canvas_id=DEMO_CANVAS_ID,
            type="document",
            title="approved-pilot-brief.md",
            text="",
            position_x=40,
            position_y=60,
            width=340,
            height=280,
            **_timestamps(),
        ),
        CanvasNode(
            id=DEMO_INSUFFICIENT_NODE_ID,
            canvas_id=DEMO_CANVAS_ID,
            type="ai_response",
            title="[Replay] Insufficient evidence example",
            text=INSUFFICIENT_RESPONSE,
            position_x=890,
            position_y=740,
            width=460,
            height=280,
            **_timestamps(),
        ),
        CanvasNode(
            id=DOCUMENT_TWO_NODE_ID,
            canvas_id=DEMO_CANVAS_ID,
            type="document",
            title="research-and-contingency.md",
            text="",
            position_x=40,
            position_y=390,
            width=340,
            height=280,
            **_timestamps(),
        ),
        CanvasNode(
            id=NOTE_HYPOTHESIS_ID,
            canvas_id=DEMO_CANVAS_ID,
            type="note",
            title="Team hypothesis — inference",
            text=(
                "Guided onboarding may improve adoption. Treat this as an inference, not a "
                "sourced fact."
            ),
            position_x=460,
            position_y=420,
            width=330,
            height=220,
            **_timestamps(),
        ),
        CanvasNode(
            id=NOTE_CONTROL_ID,
            canvas_id=DEMO_CANVAS_ID,
            type="note",
            title="Selected context and user control",
            text=(
                "Replay selection: both source documents plus the team hypothesis. "
                "The persisted execution records retain exact node snapshots and retrieval ranks."
            ),
            position_x=460,
            position_y=80,
            width=330,
            height=220,
            **_timestamps(),
        ),
        CanvasNode(
            id=DEMO_RESPONSE_NODE_ID,
            canvas_id=DEMO_CANVAS_ID,
            type="ai_response",
            title="[Replay] Grounded launch synthesis",
            text=REPLAY_RESPONSE,
            position_x=890,
            position_y=180,
            width=460,
            height=520,
            **_timestamps(),
        ),
    ]


def _documents() -> list[Document]:
    return [
        _document(DOCUMENT_ONE_ID, "approved-pilot-brief.md", LAUNCH_BRIEF),
        _document(DOCUMENT_TWO_ID, "research-and-contingency.md", INTERVIEW_SUMMARY),
    ]


def _document(document_id: uuid.UUID, name: str, content: str) -> Document:
    encoded = content.encode()
    return Document(
        id=document_id,
        canvas_id=DEMO_CANVAS_ID,
        file_name=name,
        file_type="markdown",
        media_type="text/markdown",
        file_size_bytes=len(encoded),
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        status="ready",
        processing_stage="ready",
        page_count=None,
        chunk_count=1,
        extracted_text=content,
        error_message=None,
        **_timestamps(),
    )


def _document_records() -> list[object]:
    records: list[object] = []
    for offset, (document_id, node_id, chunk_id, name, content) in enumerate(
        [
            (
                DOCUMENT_ONE_ID,
                DOCUMENT_ONE_NODE_ID,
                CHUNK_ONE_ID,
                "approved-pilot-brief.md",
                LAUNCH_BRIEF,
            ),
            (
                DOCUMENT_TWO_ID,
                DOCUMENT_TWO_NODE_ID,
                CHUNK_TWO_ID,
                "research-and-contingency.md",
                INTERVIEW_SUMMARY,
            ),
        ],
        start=1,
    ):
        encoded = content.encode()
        storage_key = f"{document_id.hex}/{name}"
        records.extend(
            [
                DocumentFile(
                    id=_id(140 + offset),
                    document_id=document_id,
                    storage_key=storage_key,
                    byte_size=len(encoded),
                    sha256=hashlib.sha256(encoded).hexdigest(),
                    media_type="text/markdown",
                    **_timestamps(),
                ),
                CanvasDocumentNode(
                    node_id=node_id,
                    canvas_id=DEMO_CANVAS_ID,
                    document_id=document_id,
                    **_timestamps(),
                ),
                DocumentChunk(
                    id=chunk_id,
                    document_id=document_id,
                    chunk_index=0,
                    content=content,
                    page_number=None,
                    heading=(
                        "Approved pilot brief" if offset == 1 else "Research and contingency notes"
                    ),
                    char_start=0,
                    char_end=len(content),
                    **_timestamps(),
                ),
                DocumentProcessingJob(
                    id=_id(160 + offset),
                    user_id=DEMO_USER_ID,
                    workspace_id=DEMO_CANVAS_ID,
                    document_id=document_id,
                    attempt=1,
                    status="ready",
                    error_message=None,
                    started_at=DEMO_TIMESTAMP,
                    completed_at=DEMO_TIMESTAMP,
                    **_timestamps(),
                ),
            ]
        )
    return records


def _ai_records() -> list[object]:
    request = AIRequest(
        id=DEMO_REQUEST_ID,
        trace_id=DEMO_TRACE_ID,
        user_id=DEMO_USER_ID,
        workspace_id=DEMO_CANVAS_ID,
        canvas_id=DEMO_CANVAS_ID,
        instruction=(
            "Reconcile the approved launch facts, onboarding inference, contingency-date conflict, "
            "and any unsupported retention claim."
        ),
        selected_node_ids=[
            str(DOCUMENT_ONE_NODE_ID),
            str(DOCUMENT_TWO_NODE_ID),
            str(NOTE_HYPOTHESIS_ID),
        ],
        context_snapshot=[
            {
                "id": str(NOTE_HYPOTHESIS_ID),
                "title": "Team hypothesis — inference",
                "text": (
                    "Guided onboarding may improve adoption. Treat this as an inference, not a "
                    "sourced fact."
                ),
            },
            {
                "sourceId": f"chunk_{CHUNK_ONE_ID.hex}",
                "documentId": str(DOCUMENT_ONE_ID),
                "title": "approved-pilot-brief.md",
                "text": LAUNCH_BRIEF,
            },
            {
                "sourceId": f"chunk_{CHUNK_TWO_ID.hex}",
                "documentId": str(DOCUMENT_TWO_ID),
                "title": "research-and-contingency.md",
                "text": INTERVIEW_SUMMARY,
            },
        ],
        provider="mock",
        model="deterministic-demo-replay-v1",
        status="completed",
        error=None,
        model_configuration={"mode": "replay", "externalCall": False, "temperature": None},
        retrieval_configuration={
            "topK": 2,
            "threshold": 0.2,
            "selectedDocumentIds": [str(DOCUMENT_ONE_ID), str(DOCUMENT_TWO_ID)],
        },
        prompt_version="buildweek-demo-replay-v1",
        provider_configuration_version="deterministic-demo-replay-v1",
        execution_mode="demo_replay",
        started_at=DEMO_TIMESTAMP,
        completed_at=DEMO_TIMESTAMP,
        latency_ms=0,
        **_timestamps(),
    )
    response = AIResponse(
        id=DEMO_RESPONSE_ID,
        request_id=DEMO_REQUEST_ID,
        node_id=DEMO_RESPONSE_NODE_ID,
        content=REPLAY_RESPONSE,
        provider_response_id=None,
        grounded=True,
        insufficient_evidence=False,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        **_timestamps(),
    )
    insufficient_request = AIRequest(
        id=DEMO_INSUFFICIENT_REQUEST_ID,
        trace_id=DEMO_INSUFFICIENT_TRACE_ID,
        user_id=DEMO_USER_ID,
        workspace_id=DEMO_CANVAS_ID,
        canvas_id=DEMO_CANVAS_ID,
        instruction="What is the project CEO's favorite color?",
        selected_node_ids=[str(DOCUMENT_ONE_NODE_ID), str(DOCUMENT_TWO_NODE_ID)],
        context_snapshot=[],
        provider="mock",
        model="deterministic-demo-replay-v1",
        status="completed",
        error=None,
        model_configuration={"mode": "replay", "externalCall": False, "temperature": None},
        retrieval_configuration={
            "topK": 2,
            "threshold": 0.2,
            "selectedDocumentIds": [str(DOCUMENT_ONE_ID), str(DOCUMENT_TWO_ID)],
        },
        prompt_version="buildweek-demo-replay-v1",
        provider_configuration_version="deterministic-demo-replay-v1",
        execution_mode="demo_replay",
        started_at=DEMO_TIMESTAMP,
        completed_at=DEMO_TIMESTAMP,
        latency_ms=0,
        **_timestamps(),
    )
    insufficient_response = AIResponse(
        id=DEMO_INSUFFICIENT_RESPONSE_ID,
        request_id=DEMO_INSUFFICIENT_REQUEST_ID,
        node_id=DEMO_INSUFFICIENT_NODE_ID,
        content=INSUFFICIENT_RESPONSE,
        provider_response_id=None,
        grounded=False,
        insufficient_evidence=True,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        **_timestamps(),
    )
    return [request, response, insufficient_request, insufficient_response]


def _ai_provenance_records() -> list[object]:
    source_one = f"chunk_{CHUNK_ONE_ID.hex}"
    source_two = f"chunk_{CHUNK_TWO_ID.hex}"
    records: list[object] = [
        AIExecutionNode(
            id=_id(201),
            request_id=DEMO_REQUEST_ID,
            node_id=DOCUMENT_ONE_NODE_ID,
            selected_order=0,
            node_type="document",
            node_revision=0,
            title_snapshot="approved-pilot-brief.md",
            content_snapshot=json.dumps(
                {"documentId": str(DOCUMENT_ONE_ID), "status": "ready"}, sort_keys=True
            ),
            document_id=DOCUMENT_ONE_ID,
            **_timestamps(),
        ),
        AIExecutionNode(
            id=_id(202),
            request_id=DEMO_REQUEST_ID,
            node_id=DOCUMENT_TWO_NODE_ID,
            selected_order=1,
            node_type="document",
            node_revision=0,
            title_snapshot="research-and-contingency.md",
            content_snapshot=json.dumps(
                {"documentId": str(DOCUMENT_TWO_ID), "status": "ready"}, sort_keys=True
            ),
            document_id=DOCUMENT_TWO_ID,
            **_timestamps(),
        ),
        AIExecutionNode(
            id=_id(203),
            request_id=DEMO_REQUEST_ID,
            node_id=NOTE_HYPOTHESIS_ID,
            selected_order=2,
            node_type="note",
            node_revision=0,
            title_snapshot="Team hypothesis — inference",
            content_snapshot=(
                "Guided onboarding may improve adoption. Treat this as an inference, not a "
                "sourced fact."
            ),
            document_id=None,
            **_timestamps(),
        ),
        AIExecutionChunk(
            id=_id(211),
            request_id=DEMO_REQUEST_ID,
            chunk_id=CHUNK_ONE_ID,
            document_id=DOCUMENT_ONE_ID,
            rank=1,
            score=0.91,
            included_in_context=True,
            exclusion_reason=None,
            source_id_snapshot=source_one,
            document_name_snapshot="approved-pilot-brief.md",
            content_snapshot=LAUNCH_BRIEF,
            page_number_snapshot=None,
            heading_snapshot="Approved pilot brief",
            char_start_snapshot=0,
            char_end_snapshot=len(LAUNCH_BRIEF),
            **_timestamps(),
        ),
        AIExecutionChunk(
            id=_id(212),
            request_id=DEMO_REQUEST_ID,
            chunk_id=CHUNK_TWO_ID,
            document_id=DOCUMENT_TWO_ID,
            rank=2,
            score=0.84,
            included_in_context=True,
            exclusion_reason=None,
            source_id_snapshot=source_two,
            document_name_snapshot="research-and-contingency.md",
            content_snapshot=INTERVIEW_SUMMARY,
            page_number_snapshot=None,
            heading_snapshot="Research and contingency notes",
            char_start_snapshot=0,
            char_end_snapshot=len(INTERVIEW_SUMMARY),
            **_timestamps(),
        ),
    ]
    claims = [
        (
            source_one,
            DOCUMENT_ONE_ID,
            CHUNK_ONE_ID,
            "Approved launch facts and date",
            LAUNCH_BRIEF,
            "approved-pilot-brief.md",
            "Approved pilot brief",
        ),
        (
            source_two,
            DOCUMENT_TWO_ID,
            CHUNK_TWO_ID,
            "Contingency date and unsupported retention target",
            INTERVIEW_SUMMARY,
            "research-and-contingency.md",
            "Research and contingency notes",
        ),
    ]
    for ordinal, (source_id, document_id, chunk_id, claim, excerpt, name, heading) in enumerate(
        claims, start=1
    ):
        records.extend(
            [
                Citation(
                    id=_id(220 + ordinal),
                    ai_response_id=DEMO_RESPONSE_ID,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    identifier=source_id,
                    claim=claim,
                    quote=excerpt,
                    ordinal=ordinal,
                    **_timestamps(),
                ),
                AIExecutionCitation(
                    id=_id(230 + ordinal),
                    request_id=DEMO_REQUEST_ID,
                    ai_response_id_snapshot=DEMO_RESPONSE_ID,
                    ordinal=ordinal,
                    source_id_snapshot=source_id,
                    claim_snapshot=claim,
                    excerpt_snapshot=excerpt,
                    document_id_snapshot=document_id,
                    chunk_id_snapshot=chunk_id,
                    document_name_snapshot=name,
                    page_number_snapshot=None,
                    heading_snapshot=heading,
                    char_start_snapshot=0,
                    char_end_snapshot=len(excerpt),
                    **_timestamps(),
                ),
                AIResponseSource(
                    id=_id(240 + ordinal),
                    ai_response_id=DEMO_RESPONSE_ID,
                    document_id=document_id,
                    document_node_id=(
                        DOCUMENT_ONE_NODE_ID if ordinal == 1 else DOCUMENT_TWO_NODE_ID
                    ),
                    max_relevance_score=(0.91 if ordinal == 1 else 0.84),
                    **_timestamps(),
                ),
                AIExecutionSource(
                    id=_id(250 + ordinal),
                    request_id=DEMO_REQUEST_ID,
                    response_node_id_snapshot=DEMO_RESPONSE_NODE_ID,
                    document_id_snapshot=document_id,
                    document_node_id_snapshot=(
                        DOCUMENT_ONE_NODE_ID if ordinal == 1 else DOCUMENT_TWO_NODE_ID
                    ),
                    document_name_snapshot=name,
                    max_relevance_score=(0.91 if ordinal == 1 else 0.84),
                    **_timestamps(),
                ),
            ]
        )
    records.extend(
        [
            AIExecutionNode(
                id=_id(261),
                request_id=DEMO_INSUFFICIENT_REQUEST_ID,
                node_id=DOCUMENT_ONE_NODE_ID,
                selected_order=0,
                node_type="document",
                node_revision=0,
                title_snapshot="approved-pilot-brief.md",
                content_snapshot=json.dumps(
                    {"documentId": str(DOCUMENT_ONE_ID), "status": "ready"}, sort_keys=True
                ),
                document_id=DOCUMENT_ONE_ID,
                **_timestamps(),
            ),
            AIExecutionNode(
                id=_id(262),
                request_id=DEMO_INSUFFICIENT_REQUEST_ID,
                node_id=DOCUMENT_TWO_NODE_ID,
                selected_order=1,
                node_type="document",
                node_revision=0,
                title_snapshot="research-and-contingency.md",
                content_snapshot=json.dumps(
                    {"documentId": str(DOCUMENT_TWO_ID), "status": "ready"}, sort_keys=True
                ),
                document_id=DOCUMENT_TWO_ID,
                **_timestamps(),
            ),
            AIExecutionChunk(
                id=_id(271),
                request_id=DEMO_INSUFFICIENT_REQUEST_ID,
                chunk_id=CHUNK_ONE_ID,
                document_id=DOCUMENT_ONE_ID,
                rank=1,
                score=0.03,
                included_in_context=False,
                exclusion_reason="below_relevance_threshold",
                source_id_snapshot=source_one,
                document_name_snapshot="approved-pilot-brief.md",
                content_snapshot=LAUNCH_BRIEF,
                page_number_snapshot=None,
                heading_snapshot="Approved pilot brief",
                char_start_snapshot=0,
                char_end_snapshot=len(LAUNCH_BRIEF),
                **_timestamps(),
            ),
            AIExecutionChunk(
                id=_id(272),
                request_id=DEMO_INSUFFICIENT_REQUEST_ID,
                chunk_id=CHUNK_TWO_ID,
                document_id=DOCUMENT_TWO_ID,
                rank=2,
                score=0.01,
                included_in_context=False,
                exclusion_reason="below_relevance_threshold",
                source_id_snapshot=source_two,
                document_name_snapshot="research-and-contingency.md",
                content_snapshot=INTERVIEW_SUMMARY,
                page_number_snapshot=None,
                heading_snapshot="Research and contingency notes",
                char_start_snapshot=0,
                char_end_snapshot=len(INTERVIEW_SUMMARY),
                **_timestamps(),
            ),
        ]
    )
    return records


def _edges() -> list[Edge]:
    pairs = [
        (DOCUMENT_ONE_NODE_ID, DEMO_RESPONSE_NODE_ID, "generated_from", "selected context"),
        (DOCUMENT_TWO_NODE_ID, DEMO_RESPONSE_NODE_ID, "generated_from", "selected context"),
        (NOTE_HYPOTHESIS_ID, DEMO_RESPONSE_NODE_ID, "generated_from", "selected context"),
        (DEMO_RESPONSE_NODE_ID, DOCUMENT_ONE_NODE_ID, "cites", "supports claim"),
        (DEMO_RESPONSE_NODE_ID, DOCUMENT_TWO_NODE_ID, "cites", "supports claim"),
        (NOTE_CONTROL_ID, NOTE_HYPOTHESIS_ID, "default", "classifies inference"),
        (
            DOCUMENT_ONE_NODE_ID,
            DEMO_INSUFFICIENT_NODE_ID,
            "generated_from",
            "selected but insufficient",
        ),
        (
            DOCUMENT_TWO_NODE_ID,
            DEMO_INSUFFICIENT_NODE_ID,
            "generated_from",
            "selected but insufficient",
        ),
    ]
    return [
        Edge(
            id=_id(300 + index),
            canvas_id=DEMO_CANVAS_ID,
            source_node_id=source,
            target_node_id=target,
            kind=kind,
            label=label,
            **_timestamps(),
        )
        for index, (source, target, kind, label) in enumerate(pairs, start=1)
    ]


def _trace_events() -> list[TraceEvent]:
    base = dict(
        trace_id=DEMO_TRACE_ID,
        parent_trace_id=None,
        occurred_at=DEMO_TIMESTAMP,
        event_type="demo.grounded_replay",
        actor_id="buildweek-demo",
        actor_type="system",
        user_id=DEMO_USER_ID,
        workspace_id=DEMO_CANVAS_ID,
        object_id=DEMO_REQUEST_ID,
        object_type="ai_execution",
        operation="replay_grounded_answer",
        error_payload=None,
    )
    insufficient_base = dict(
        trace_id=DEMO_INSUFFICIENT_TRACE_ID,
        parent_trace_id=None,
        occurred_at=DEMO_TIMESTAMP,
        event_type="demo.insufficient_evidence_replay",
        actor_id="buildweek-demo",
        actor_type="system",
        user_id=DEMO_USER_ID,
        workspace_id=DEMO_CANVAS_ID,
        object_id=DEMO_INSUFFICIENT_REQUEST_ID,
        object_type="ai_execution",
        operation="replay_insufficient_evidence",
        error_payload=None,
    )
    return [
        TraceEvent(
            event_id=_id(401),
            status="started",
            metadata_payload={
                "mode": "deterministic_replay",
                "externalCall": False,
                "selectedNodeIds": [
                    str(DOCUMENT_ONE_NODE_ID),
                    str(DOCUMENT_TWO_NODE_ID),
                    str(NOTE_HYPOTHESIS_ID),
                ],
            },
            **base,
        ),
        TraceEvent(
            event_id=_id(402),
            status="succeeded",
            metadata_payload={
                "requestId": str(DEMO_REQUEST_ID),
                "responseId": str(DEMO_RESPONSE_ID),
                "retrievedChunkIds": [str(CHUNK_ONE_ID), str(CHUNK_TWO_ID)],
                "retrievalRanks": [1, 2],
                "validatedCitationIds": [str(_id(221)), str(_id(222))],
                "claimClasses": ["supported", "inference", "conflict", "unsupported"],
                "model": "deterministic-demo-replay-v1",
                "tokenUsage": None,
            },
            **base,
        ),
        TraceEvent(
            event_id=_id(403),
            status="started",
            metadata_payload={
                "mode": "deterministic_replay",
                "externalCall": False,
                "selectedNodeIds": [str(DOCUMENT_ONE_NODE_ID), str(DOCUMENT_TWO_NODE_ID)],
            },
            **insufficient_base,
        ),
        TraceEvent(
            event_id=_id(404),
            status="succeeded",
            metadata_payload={
                "requestId": str(DEMO_INSUFFICIENT_REQUEST_ID),
                "responseId": str(DEMO_INSUFFICIENT_RESPONSE_ID),
                "includedChunkIds": [],
                "validatedCitationIds": [],
                "insufficientEvidence": True,
                "model": "deterministic-demo-replay-v1",
                "tokenUsage": None,
            },
            **insufficient_base,
        ),
    ]


def _canonical_records() -> tuple[list[CanonicalObject], list[object]]:
    document_one_object = _id(501)
    document_two_object = _id(502)
    chunk_one_object = _id(503)
    chunk_two_object = _id(504)
    note_object = _id(505)
    execution_object = _id(506)
    relationship_specs = [
        (_id(511), document_one_object, execution_object, "references"),
        (_id(512), document_two_object, execution_object, "references"),
        (_id(513), note_object, execution_object, "derived_from"),
    ]
    typed = [
        (document_one_object, "document"),
        (document_two_object, "document"),
        (chunk_one_object, "chunk"),
        (chunk_two_object, "chunk"),
        (note_object, "note"),
        (execution_object, "execution"),
        *((relationship_id, "relationship") for relationship_id, _, _, _ in relationship_specs),
    ]
    objects = [
        CanonicalObject(
            id=object_id,
            workspace_id=DEMO_CANVAS_ID,
            object_type=object_type,
            version=1,
            lifecycle_state="active",
            metadata_payload={"demo": True},
            **_timestamps(),
        )
        for object_id, object_type in typed
    ]
    details: list[object] = [
        CanonicalDocument(
            object_id=document_one_object,
            display_name="approved-pilot-brief.md",
            source_type="markdown",
            processing_status="ready",
            source_metadata={"demo": True},
            legacy_document_id=DOCUMENT_ONE_ID,
        ),
        CanonicalDocument(
            object_id=document_two_object,
            display_name="research-and-contingency.md",
            source_type="markdown",
            processing_status="ready",
            source_metadata={"demo": True},
            legacy_document_id=DOCUMENT_TWO_ID,
        ),
        CanonicalChunk(
            object_id=chunk_one_object,
            document_object_id=document_one_object,
            ordered_position=0,
            content=LAUNCH_BRIEF,
            source_location={
                "heading": "Approved pilot brief",
                "charStart": 0,
                "charEnd": len(LAUNCH_BRIEF),
            },
        ),
        CanonicalChunk(
            object_id=chunk_two_object,
            document_object_id=document_two_object,
            ordered_position=0,
            content=INTERVIEW_SUMMARY,
            source_location={
                "heading": "Research and contingency notes",
                "charStart": 0,
                "charEnd": len(INTERVIEW_SUMMARY),
            },
        ),
        CanonicalNote(
            object_id=note_object,
            title="Team hypothesis — inference",
            content="Guided onboarding may improve adoption; not a sourced fact.",
        ),
        CanonicalExecution(
            object_id=execution_object,
            execution_type="grounded_demo_replay",
            status="succeeded",
            started_at=DEMO_TIMESTAMP,
            completed_at=DEMO_TIMESTAMP,
            trace_id=DEMO_TRACE_ID,
            inputs_metadata={
                "selectedNodeIds": [
                    str(DOCUMENT_ONE_NODE_ID),
                    str(DOCUMENT_TWO_NODE_ID),
                    str(NOTE_HYPOTHESIS_ID),
                ]
            },
            outputs_metadata={"responseId": str(DEMO_RESPONSE_ID), "mode": "replay"},
            failure=None,
        ),
    ]
    details.extend(
        CanonicalRelationship(
            object_id=relationship_id,
            workspace_id=DEMO_CANVAS_ID,
            source_object_id=source,
            target_object_id=target,
            relationship_type=kind,
            created_by=None,
            trace_id=DEMO_TRACE_ID,
        )
        for relationship_id, source, target, kind in relationship_specs
    )
    return objects, details


async def _write_source_files(storage_root: Path) -> None:
    for document_id, name, content in [
        (DOCUMENT_ONE_ID, "approved-pilot-brief.md", LAUNCH_BRIEF),
        (DOCUMENT_TWO_ID, "research-and-contingency.md", INTERVIEW_SUMMARY),
    ]:
        directory = storage_root / document_id.hex
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(content, encoding="utf-8")


async def demo_is_seeded(session: AsyncSession) -> bool:
    return (await session.scalar(select(Canvas.id).where(Canvas.id == DEMO_CANVAS_ID))) is not None


async def validate_demo_seed(session: AsyncSession, storage_root: Path) -> None:
    """Fail closed when any required replay or provenance invariant is missing."""

    if not await demo_is_seeded(session):
        raise RuntimeError("The deterministic demo workspace is not seeded.")
    counts = {
        "documents": await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.id.in_((DOCUMENT_ONE_ID, DOCUMENT_TWO_ID)))
        ),
        "citations": await session.scalar(
            select(func.count())
            .select_from(Citation)
            .where(Citation.ai_response_id == DEMO_RESPONSE_ID)
        ),
        "sources": await session.scalar(
            select(func.count())
            .select_from(AIResponseSource)
            .where(AIResponseSource.ai_response_id == DEMO_RESPONSE_ID)
        ),
        "trace_events": await session.scalar(
            select(func.count())
            .select_from(TraceEvent)
            .where(TraceEvent.workspace_id == DEMO_CANVAS_ID)
        ),
    }
    expected = {"documents": 2, "citations": 2, "sources": 2, "trace_events": 4}
    if counts != expected:
        raise RuntimeError(f"Demo provenance is incomplete: expected {expected}, found {counts}")

    grounded = await session.get(AIResponse, DEMO_RESPONSE_ID)
    insufficient = await session.get(AIResponse, DEMO_INSUFFICIENT_RESPONSE_ID)
    if grounded is None or not grounded.grounded or grounded.insufficient_evidence:
        raise RuntimeError("The grounded replay response is missing or incorrectly classified.")
    if insufficient is None or insufficient.grounded or not insufficient.insufficient_evidence:
        raise RuntimeError("The insufficient-evidence replay is missing or incorrectly classified.")
    insufficient_citations = await session.scalar(
        select(func.count())
        .select_from(Citation)
        .where(Citation.ai_response_id == DEMO_INSUFFICIENT_RESPONSE_ID)
    )
    if insufficient_citations != 0:
        raise RuntimeError("The insufficient-evidence replay must not contain citations.")

    excluded = (
        await session.scalars(
            select(AIExecutionChunk).where(
                AIExecutionChunk.request_id == DEMO_INSUFFICIENT_REQUEST_ID
            )
        )
    ).all()
    if len(excluded) != 2 or any(chunk.included_in_context for chunk in excluded):
        raise RuntimeError("Insufficient-evidence retrieval exclusions are incomplete.")

    expected_files = [
        storage_root / DOCUMENT_ONE_ID.hex / "approved-pilot-brief.md",
        storage_root / DOCUMENT_TWO_ID.hex / "research-and-contingency.md",
    ]
    if any(not path.is_file() for path in expected_files):
        raise RuntimeError("One or more deterministic demo source files are unavailable.")


__all__ = [
    "DEMO_CANVAS_ID",
    "DEMO_REQUEST_ID",
    "DEMO_RESPONSE_ID",
    "DEMO_TRACE_ID",
    "DemoSeedResult",
    "demo_is_seeded",
    "seed_demo",
    "validate_demo_seed",
]
