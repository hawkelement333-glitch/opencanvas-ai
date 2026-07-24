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
    Citation,
    ControlledAgentExecutionState,
    ControlledAgentStateTransition,
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
