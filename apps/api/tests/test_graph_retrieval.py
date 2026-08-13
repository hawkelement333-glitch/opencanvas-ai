from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Base,
    DomainEventOutbox,
    DomainEventRecord,
    GraphRetrievalCitation,
    GraphRetrievalDecision,
    GraphRetrievalRun,
    TraceEvent,
    TraceEvidenceBundle,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.documents.embeddings import MockEmbeddingProvider
from opencanvas_api.services.graph_retrieval import (
    EXCLUSION_REASONS,
    INCLUSION_REASONS,
    RELATIONSHIP_DIRECTIONS,
    RETRIEVAL_OUTCOMES,
    GraphAwareRetrievalService,
    GraphRetrievalConflictError,
    GraphRetrievalNotFoundError,
    GraphRetrievalStorageError,
    StartGraphRetrieval,
    TraceEvidenceBundleService,
)
from opencanvas_api.services.knowledge_graph import KnowledgeGraphService
from tests.test_knowledge_graph_foundation import _create, _foundation


async def _retrieval_foundation(
    database: Database,
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    canvas_id, objects = await _foundation(database)
    async with database.sessions() as session:
        await KnowledgeGraphService(session).create_relationship(
            _create(
                canvas_id,
                objects,
                "related_to",
                "note_one",
                "note",
                "note_two",
                "note",
                "retrieval-related",
            )
        )
        await session.commit()
    return canvas_id, objects


def _command(
    canvas_id: uuid.UUID,
    objects: dict[str, uuid.UUID],
    *,
    key: str = "retrieval-one",
) -> StartGraphRetrieval:
    return StartGraphRetrieval(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id,
        query="First",
        selected_object_ids=(objects["note_one"], objects["note_two"]),
        seed_object_ids=(objects["note_one"],),
        idempotency_key=key,
        max_depth=2,
        top_k=8,
        min_relevance=0.15,
    )


@pytest.mark.anyio
async def test_selected_graph_retrieval_is_deterministic_exact_and_replay_safe(
    database: Database,
) -> None:
    canvas_id, objects = await _retrieval_foundation(database)
    async with database.sessions() as session:
        service = GraphAwareRetrievalService(
            session,
            embedding_provider=MockEmbeddingProvider(),
        )
        command = _command(canvas_id, objects)
        first = await service.retrieve(command)
        replay = await service.retrieve(command)
        assert replay.duplicate is True
        assert replay.run.retrieval_id == first.run.retrieval_id
        assert first.run.outcome == "supported"
        assert first.run.graph_revision == 1
        assert [item.excerpt for item in first.citations] == ["First"]
        citation = first.citations[0]
        assert citation.canonical_object_id == objects["note_one"]
        assert citation.source_sha256 == hashlib.sha256(b"First").hexdigest()
        assert citation.excerpt_sha256 == hashlib.sha256(b"First").hexdigest()
        assert citation.locator == {"charStart": 0, "charEnd": 5}
        assert any(
            item.reason_code == "graph_related_candidate" and item.object_id == objects["note_two"]
            for item in first.decisions
        )
        with pytest.raises(GraphRetrievalConflictError):
            await service.retrieve(replace(command, query="Different"))
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GraphRetrievalRun)) == 1
        assert await session.scalar(select(func.count()).select_from(GraphRetrievalCitation)) == 1
        traces = (
            await session.scalars(
                select(TraceEvent).where(TraceEvent.operation == "graph_retrieval.execute")
            )
        ).all()
        assert [item.status for item in traces] == ["started", "succeeded"]


@pytest.mark.anyio
async def test_retrieval_replay_and_read_revalidate_current_workspace_scope(
    database: Database,
) -> None:
    canvas_id, objects = await _retrieval_foundation(database)
    command = _command(canvas_id, objects, key="revalidate-current-scope")
    async with database.sessions() as session:
        service = GraphAwareRetrievalService(session, embedding_provider=MockEmbeddingProvider())
        record = await service.retrieve(command)
        bundle = await TraceEvidenceBundleService(session).generate(
            record,
            user_id=SYSTEM_USER_ID,
        )
        await session.commit()

    async with database.sessions() as session:
        workspace = await session.get(Workspace, SYSTEM_WORKSPACE_ID)
        assert workspace is not None
        workspace.lifecycle_state = "deleted"
        workspace.deleted_at = datetime.now(UTC)
        await session.commit()

    async with database.sessions() as session:
        service = GraphAwareRetrievalService(session, embedding_provider=MockEmbeddingProvider())
        with pytest.raises(GraphRetrievalNotFoundError):
            await service.get_owned(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                retrieval_id=record.run.retrieval_id,
            )
        with pytest.raises(GraphRetrievalNotFoundError):
            await service.retrieve(command)
        with pytest.raises(GraphRetrievalNotFoundError):
            await TraceEvidenceBundleService(session).get_owned(
                bundle_id=bundle.bundle_id,
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
            )


@pytest.mark.anyio
async def test_relationship_cannot_bypass_selected_context(database: Database) -> None:
    canvas_id, objects = await _retrieval_foundation(database)
    async with database.sessions() as session:
        service = GraphAwareRetrievalService(
            session,
            embedding_provider=MockEmbeddingProvider(),
        )
        result = await service.retrieve(
            replace(
                _command(canvas_id, objects, key="selected-only"),
                selected_object_ids=(objects["note_one"],),
            )
        )
        assert all(item.canonical_object_id == objects["note_one"] for item in result.citations)
        assert any(item.reason_code == "outside_selected_context" for item in result.decisions)
        with pytest.raises(GraphRetrievalNotFoundError):
            await service.retrieve(
                replace(
                    _command(canvas_id, objects, key="cross-canvas"),
                    canvas_id=uuid.uuid4(),
                )
            )


@pytest.mark.anyio
async def test_forward_relationship_direction_and_insufficient_evidence(
    database: Database,
) -> None:
    canvas_id, objects = await _foundation(database)
    async with database.sessions() as session:
        await KnowledgeGraphService(session).create_relationship(
            _create(
                canvas_id,
                objects,
                "references",
                "note_one",
                "note",
                "note_two",
                "note",
                "forward-only",
            )
        )
        await session.commit()
    async with database.sessions() as session:
        result = await GraphAwareRetrievalService(
            session,
            embedding_provider=MockEmbeddingProvider(),
        ).retrieve(
            replace(
                _command(canvas_id, objects, key="reverse-not-allowed"),
                seed_object_ids=(objects["note_two"],),
            )
        )
        assert result.run.outcome == "insufficient_evidence"
        assert result.citations == ()
        assert not any(
            item.object_id == objects["note_one"] and item.reason_code == "reference_relationship"
            for item in result.decisions
        )


@pytest.mark.anyio
@pytest.mark.parametrize("failure_point", ["run", "decisions", "citations"])
async def test_retrieval_failure_injection_leaves_no_partial_success(
    database: Database,
    failure_point: str,
) -> None:
    canvas_id, objects = await _retrieval_foundation(database)

    def fail() -> None:
        raise GraphRetrievalStorageError()

    async with database.sessions() as session:
        service = GraphAwareRetrievalService(
            session,
            embedding_provider=MockEmbeddingProvider(),
            after_run=fail if failure_point == "run" else None,
            after_decisions=fail if failure_point == "decisions" else None,
            after_citations=fail if failure_point == "citations" else None,
        )
        with pytest.raises(GraphRetrievalStorageError):
            await service.retrieve(_command(canvas_id, objects, key=f"failure-{failure_point}"))
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GraphRetrievalRun)) == 0
        assert await session.scalar(select(func.count()).select_from(GraphRetrievalDecision)) == 0
        assert await session.scalar(select(func.count()).select_from(GraphRetrievalCitation)) == 0
        traces = (
            await session.scalars(
                select(TraceEvent).where(TraceEvent.operation == "graph_retrieval.execute")
            )
        ).all()
        assert [item.status for item in traces] == ["started", "failed"]


@pytest.mark.anyio
async def test_apa_and_bundle_are_deterministic_integrity_checked_and_evented(
    database: Database,
) -> None:
    canvas_id, objects = await _retrieval_foundation(database)
    async with database.sessions() as session:
        service = GraphAwareRetrievalService(
            session,
            embedding_provider=MockEmbeddingProvider(),
        )
        record = await service.retrieve(_command(canvas_id, objects, key="bundle"))
        apa = await service.render_apa(record, user_id=SYSTEM_USER_ID)
        assert apa[0].in_text == "(One, n.d.)"
        assert apa[0].reference == "One. (n.d.). [Internal note]."
        bundles = TraceEvidenceBundleService(session)
        first = await bundles.generate(record, user_id=SYSTEM_USER_ID)
        replay = await bundles.generate(record, user_id=SYSTEM_USER_ID)
        assert replay.bundle_id == first.bundle_id
        assert replay.artifact_bytes == first.artifact_bytes
        assert first.artifact_bytes is not None
        assert first.artifact_sha256 == hashlib.sha256(first.artifact_bytes).hexdigest()
        with zipfile.ZipFile(io.BytesIO(first.artifact_bytes)) as archive:
            names = archive.namelist()
            assert names == sorted(names)
            assert {
                "README.md",
                "manifest.json",
                "trace-report.md",
                "references.md",
                "citations.json",
                "excerpts/source-001-excerpt.txt",
                "integrity/sha256sums.txt",
            } <= set(names)
            assert not any(name.startswith("authorized-sources/") for name in names)
            checksums = archive.read("integrity/sha256sums.txt").decode()
            for line in checksums.splitlines():
                digest, name = line.split("  ", 1)
                assert hashlib.sha256(archive.read(name)).hexdigest() == digest
            serialized = b"".join(archive.read(name) for name in names)
            for forbidden in (b"PRIVATE KEY", b"leaseOwner", b"chain of thought"):
                assert forbidden not in serialized
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(TraceEvidenceBundle)) == 1
        assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) == 5
        assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) == 5


def test_closed_retrieval_registries() -> None:
    assert RELATIONSHIP_DIRECTIONS == {
        "references": "forward",
        "derived_from": "forward",
        "related_to": "both",
        "cites": "forward",
        "supports": "forward",
        "contradicts": "both",
        "produced_by": "forward",
        "affected_by": "forward",
    }
    assert "selected_seed" in INCLUSION_REASONS
    assert "outside_selected_context" in EXCLUSION_REASONS
    assert {
        "supported",
        "conflicting_evidence",
        "insufficient_evidence",
        "bounded_result",
    } == RETRIEVAL_OUTCOMES


@pytest.mark.anyio
async def test_graph_retrieval_api_and_export_denial_are_scope_safe(
    database: Database,
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    canvas_id, objects = await _retrieval_foundation(database)
    endpoint = f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/canvases/{canvas_id}"
    response = await client.post(
        f"{endpoint}/graph-retrievals",
        json={
            "query": "First",
            "selectedObjectIds": [str(objects["note_one"]), str(objects["note_two"])],
            "seedObjectIds": [str(objects["note_one"])],
            "idempotencyKey": "api-retrieval",
        },
    )
    assert response.status_code == 200
    body = response.json()
    retrieval_id = body["retrievalId"]
    assert body["outcome"] == "supported"
    assert body["citations"][0]["excerpt"] == "First"
    assert "requestDigest" not in str(body)
    assert "policy" not in str(body)

    trace = await client.get(f"{endpoint}/graph-retrievals/{retrieval_id}/trace")
    assert trace.status_code == 200
    assert trace.json()["statuses"] == ["started", "succeeded"]

    rendered = await client.post(f"{endpoint}/graph-retrievals/{retrieval_id}/citations/render")
    assert rendered.status_code == 200
    assert rendered.json()["rendererVersion"] == "apa7-repository-sources-v1"

    denied = await client.post(
        f"{endpoint}/graph-retrievals/{retrieval_id}/evidence-bundle",
        json={"includeAuthorizedSources": True},
    )
    assert denied.status_code == 403

    bundle = await client.post(
        f"{endpoint}/graph-retrievals/{retrieval_id}/evidence-bundle",
        json={},
    )
    assert bundle.status_code == 200
    bundle_id = bundle.json()["bundleId"]
    download = await client.post(f"{endpoint}/evidence-bundles/{bundle_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert download.headers["x-content-type-options"] == "nosniff"

    probing = await client.get(
        f"{api_prefix}/workspaces/{uuid.uuid4()}/canvases/{canvas_id}/"
        f"graph-retrievals/{retrieval_id}"
    )
    assert probing.status_code == 404

    authority = await client.post(
        f"{endpoint}/graph-retrievals",
        json={
            "query": "First",
            "selectedObjectIds": [str(objects["note_one"])],
            "seedObjectIds": [str(objects["note_one"])],
            "idempotencyKey": "authority",
            "userId": str(SYSTEM_USER_ID),
        },
    )
    assert authority.status_code == 422


@pytest.mark.anyio
async def test_retrieval_evidence_is_append_only(database: Database) -> None:
    canvas_id, objects = await _retrieval_foundation(database)
    async with database.sessions() as session:
        record = await GraphAwareRetrievalService(
            session,
            embedding_provider=MockEmbeddingProvider(),
        ).retrieve(_command(canvas_id, objects, key="immutable"))
        await session.commit()
        record.run.outcome = "insufficient_evidence"
        with pytest.raises(ValueError, match="append-only"):
            await session.flush()
        await session.rollback()
        decision = await session.scalar(select(GraphRetrievalDecision))
        assert decision is not None
        await session.delete(decision)
        with pytest.raises(ValueError, match="append-only"):
            await session.flush()


@pytest.mark.anyio
async def test_competing_identical_retrieval_creates_one_authoritative_result(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'retrieval.db').as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.sessions() as session:
        session.add(
            User(
                id=SYSTEM_USER_ID,
                email="retrieval-concurrency@mobius.invalid",
                email_normalized="retrieval-concurrency@mobius.invalid",
                password_hash="test-only",
                display_name="Retrieval concurrency",
                email_verified=True,
            )
        )
        session.add(
            Workspace(
                id=SYSTEM_WORKSPACE_ID,
                owner_id=SYSTEM_USER_ID,
                name="Retrieval concurrency",
            )
        )
        await session.commit()
    canvas_id, objects = await _retrieval_foundation(database)
    command = _command(canvas_id, objects, key="competing-identical")

    async def create() -> uuid.UUID:
        async with database.sessions() as session:
            result = await GraphAwareRetrievalService(
                session,
                embedding_provider=MockEmbeddingProvider(),
            ).retrieve(command)
            await session.commit()
            return result.run.retrieval_id

    try:
        results = await asyncio.gather(create(), create(), return_exceptions=True)
        successes = [value for value in results if isinstance(value, uuid.UUID)]
        failures = [value for value in results if isinstance(value, BaseException)]
        assert successes
        assert len(set(successes)) == 1
        assert all(isinstance(value, GraphRetrievalStorageError) for value in failures)
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(GraphRetrievalRun)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(GraphRetrievalCitation)) == 1
            )
    finally:
        await database.dispose()
