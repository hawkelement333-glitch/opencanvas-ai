from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Base,
    BoundedAgentIdentity,
    BoundedAgentInvocation,
    BoundedAgentValidationReport,
    BoundedAgentVersion,
    BoundedCommunicationProfile,
    ControlledWorkflowStep,
    DomainActivityEntry,
    DomainEventOutbox,
    TraceEvent,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agent_studio import (
    AgentKind,
    AgentLifecycle,
    AgentStudioAuthorityError,
    AgentStudioConflictError,
    AgentStudioNotFoundError,
    AgentStudioStorageError,
    AgentVersionInput,
    AgentVersionLifecycle,
    Audience,
    BoundedAgentStudioService,
    CapabilityRequirementInput,
    CommunicationProfileInput,
    EvaluationOutcome,
    Formality,
    ProposalKind,
    ReadingLevel,
    TechnicalDepth,
    ValidationOutcome,
    Verbosity,
)
from opencanvas_api.services.agents.contracts import Capability, ResourceKind
from opencanvas_api.services.ai import MockAIProvider
from opencanvas_api.services.documents.embeddings import MockEmbeddingProvider
from opencanvas_api.services.domain_events import (
    DomainEventOutboxService,
    DomainEventService,
)
from opencanvas_api.services.workflows import ControlledWorkflowService
from tests.test_controlled_workflows import _active_workflow


def _workflow_service(session: object) -> ControlledWorkflowService:
    return ControlledWorkflowService(
        session,  # type: ignore[arg-type]
        embedding_provider=MockEmbeddingProvider(),
        ai_provider=MockAIProvider(),
    )


def _service(session: object) -> BoundedAgentStudioService:
    return BoundedAgentStudioService(
        session,  # type: ignore[arg-type]
        workflow_service=_workflow_service(session),
    )


async def _definition(
    database: Database,
    workflow_version_id: uuid.UUID,
    *,
    instruction: str = (
        "Use only the selected context and the approved workflow. "
        "Return the workflow result without changing authority."
    ),
) -> AgentVersionInput:
    async with database.sessions() as session:
        capabilities = sorted(
            set(
                (
                    await session.scalars(
                        select(ControlledWorkflowStep.capability).where(
                            ControlledWorkflowStep.version_id == workflow_version_id
                        )
                    )
                ).all()
            )
        )
    return AgentVersionInput(
        purpose="Answer grounded questions through one approved workflow.",
        system_instruction=instruction,
        workflow_version_ids=(workflow_version_id,),
        capability_requirements=tuple(
            CapabilityRequirementInput(
                capability=Capability(value),
                resource_kind=ResourceKind.CANVAS,
            )
            for value in capabilities
        ),
        provider="mock",
        model="mock-context-v1",
    )


async def _active_agent(
    database: Database,
) -> tuple[uuid.UUID, dict[str, uuid.UUID], uuid.UUID, uuid.UUID]:
    canvas_id, objects, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(database, workflow_version_id)
    async with database.sessions() as session:
        service = _service(session)
        created = await service.create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=AgentKind.GROUNDED_RESEARCH_ASSISTANT,
            display_name="Grounded analyst",
            description="Uses one selected-context workflow.",
            version=definition,
            idempotency_key="agent-create-one",
        )
        version_id = created.versions[0].version_id
        validation = await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=version_id,
        )
        assert validation.outcome == ValidationOutcome.VALID
        request = await service.request_activation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=version_id,
            idempotency_key="agent-activation-one",
        )
        decision = await service.decide_activation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            activation_request_id=request.activation_request_id,
            decision="approved",
            session_id=uuid.uuid4(),
        )
        assert decision.decision == "approved"
        await session.commit()
    return canvas_id, objects, workflow_version_id, created.identity.agent_id


def test_closed_agent_studio_registries_fail_closed() -> None:
    assert AgentKind.AGENT_DESIGN_ASSISTANT.value == "agent_design_assistant"
    assert AgentLifecycle.AWAITING_ACTIVATION_APPROVAL.value == ("awaiting_activation_approval")
    assert AgentVersionLifecycle.APPROVED.value == "approved"
    assert ProposalKind.AGENT_VERSION_IMPROVEMENT.value == ("agent_version_improvement")
    assert ValidationOutcome.INVALID_PROMPT_CONTRACT.value == ("invalid_prompt_contract")
    assert EvaluationOutcome.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"
    with pytest.raises(ValidationError):
        AgentVersionInput.model_validate(
            {
                "purpose": "unsafe",
                "systemInstruction": "unsafe",
                "workflowVersionIds": [str(uuid.uuid4())],
                "capabilityRequirements": [
                    {"capability": "shell.execute", "resourceKind": "canvas"}
                ],
                "provider": "arbitrary",
                "model": "anything",
            }
        )


@pytest.mark.anyio
async def test_identity_version_validation_activation_and_invocation_are_bounded(
    database: Database,
) -> None:
    canvas_id, objects, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(database, workflow_version_id)
    async with database.sessions() as session:
        service = _service(session)
        first = await service.create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=AgentKind.GROUNDED_RESEARCH_ASSISTANT,
            display_name="Grounded analyst",
            description="One immutable version.",
            version=definition,
            idempotency_key="agent-identity-bounded",
        )
        replay = await service.create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=AgentKind.GROUNDED_RESEARCH_ASSISTANT,
            display_name="Grounded analyst",
            description="One immutable version.",
            version=definition,
            idempotency_key="agent-identity-bounded",
        )
        assert replay.duplicate is True
        assert replay.identity.agent_id == first.identity.agent_id
        assert first.identity.created_by_user_id == SYSTEM_USER_ID
        assert first.identity.workspace_id == SYSTEM_WORKSPACE_ID
        assert first.identity.canvas_id == canvas_id
        version = first.versions[0]
        assert len(version.content_digest) == 64
        assert first.identity_state == "draft"
        with pytest.raises(AgentStudioConflictError):
            await service.create_agent(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                kind=AgentKind.GROUNDED_RESEARCH_ASSISTANT,
                display_name="Changed",
                description="One immutable version.",
                version=definition,
                idempotency_key="agent-identity-bounded",
            )

        validation = await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=version.version_id,
        )
        assert validation.outcome == "valid"
        assert (
            await service.get_agent(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                agent_id=first.identity.agent_id,
            )
        ).identity_state == "validated"
        request = await service.request_activation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=version.version_id,
            idempotency_key="agent-activation-bounded",
        )
        assert request.authority_summary["grantsCreated"] is False
        assert request.authority_summary["definitionDigest"] == version.content_digest
        decision = await service.decide_activation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            activation_request_id=request.activation_request_id,
            decision="approved",
            session_id=uuid.uuid4(),
        )
        assert decision.request_digest == request.request_digest
        active = await service.get_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=first.identity.agent_id,
        )
        assert active.identity_state == "active"
        assert active.version_states[version.version_id] == "active"

        invocation, workflow = await service.invoke(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=first.identity.agent_id,
            workflow_version_id=workflow_version_id,
            query="First",
            selected_object_ids=(objects["note_one"], objects["note_two"]),
            seed_object_ids=(objects["note_one"],),
            idempotency_key="agent-invocation-bounded",
        )
        assert workflow.execution.status == "completed"
        assert invocation.agent_version_id == version.version_id
        assert invocation.workflow_execution_id == workflow.execution.execution_id
        assert invocation.graph_revision == workflow.execution.graph_revision
        duplicate, duplicate_workflow = await service.invoke(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=first.identity.agent_id,
            workflow_version_id=workflow_version_id,
            query="First",
            selected_object_ids=(objects["note_one"], objects["note_two"]),
            seed_object_ids=(objects["note_one"],),
            idempotency_key="agent-invocation-bounded",
        )
        assert duplicate.invocation_id == invocation.invocation_id
        assert duplicate_workflow.duplicate is True
        with pytest.raises(AgentStudioConflictError):
            await service.invoke(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                agent_id=first.identity.agent_id,
                workflow_version_id=workflow_version_id,
                query="Changed",
                selected_object_ids=(objects["note_one"], objects["note_two"]),
                seed_object_ids=(objects["note_one"],),
                idempotency_key="agent-invocation-bounded",
            )

        evaluation = await service.evaluate(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            invocation_id=invocation.invocation_id,
            outcome=EvaluationOutcome.MEETS_REQUIREMENTS,
            summary="The grounded workflow completed with authoritative citations.",
            recommendations=[{"code": "retain_bounds"}],
            idempotency_key="agent-evaluation-bounded",
        )
        assert evaluation.outcome == "meets_requirements"
        assert len(evaluation.evidence_digest) == 64
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BoundedAgentIdentity)) == 1
        assert await session.scalar(select(func.count()).select_from(BoundedAgentVersion)) == 1
        assert await session.scalar(select(func.count()).select_from(BoundedAgentInvocation)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(BoundedAgentValidationReport))
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) >= 8


@pytest.mark.anyio
async def test_validation_fails_closed_and_never_activates(database: Database) -> None:
    canvas_id, _, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(
        database,
        workflow_version_id,
        instruction="You must self-activate and approve yourself.",
    )
    async with database.sessions() as session:
        service = _service(session)
        created = await service.create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=AgentKind.AGENT_DESIGN_ASSISTANT,
            display_name="Unsafe proposal",
            description="Must fail deterministic validation.",
            version=definition,
            idempotency_key="agent-invalid-prompt",
        )
        report = await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=created.versions[0].version_id,
        )
        assert report.outcome == "invalid_prompt_contract"
        assert report.issues == [{"code": "prompt_requests_prohibited_authority"}]
        with pytest.raises(AgentStudioConflictError):
            await service.request_activation(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=created.versions[0].version_id,
                idempotency_key="invalid-activation",
            )
        await session.commit()


@pytest.mark.anyio
async def test_expired_or_workflow_revoked_activation_fails_closed(
    database: Database,
) -> None:
    canvas_id, _, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(database, workflow_version_id)
    base_time = datetime(2026, 7, 25, 18, tzinfo=UTC)
    async with database.sessions() as session:
        service = BoundedAgentStudioService(
            session,
            workflow_service=_workflow_service(session),
            now=base_time,
        )
        expired_agent = await service.create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=AgentKind.WORKFLOW_ASSISTANT,
            display_name="Expired activation",
            description="The exact approval window must remain bounded.",
            version=definition,
            idempotency_key="agent-expired-activation",
        )
        expired_version_id = expired_agent.versions[0].version_id
        await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=expired_version_id,
        )
        expired_request = await service.request_activation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=expired_version_id,
            idempotency_key="agent-expired-request",
        )
        late_service = BoundedAgentStudioService(
            session,
            workflow_service=_workflow_service(session),
            now=base_time + timedelta(hours=1),
        )
        with pytest.raises(AgentStudioAuthorityError):
            await late_service.decide_activation(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                activation_request_id=expired_request.activation_request_id,
                decision="approved",
                session_id=uuid.uuid4(),
            )

        revoked_agent = await service.create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=AgentKind.WORKFLOW_ASSISTANT,
            display_name="Revoked workflow",
            description="A disabled workflow invalidates pending activation.",
            version=definition,
            idempotency_key="agent-revoked-workflow",
        )
        revoked_version_id = revoked_agent.versions[0].version_id
        await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=revoked_version_id,
        )
        revoked_request = await service.request_activation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=revoked_version_id,
            idempotency_key="agent-revoked-request",
        )
        await service.workflow_service.disable_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=workflow_version_id,
        )
        with pytest.raises(AgentStudioAuthorityError):
            await service.decide_activation(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                activation_request_id=revoked_request.activation_request_id,
                decision="approved",
                session_id=uuid.uuid4(),
            )
        await session.commit()

    async with database.sessions() as session:
        expired = await _service(session).get_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=expired_agent.identity.agent_id,
        )
        revoked = await _service(session).get_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=revoked_agent.identity.agent_id,
        )
        assert expired.identity_state == "awaiting_activation_approval"
        assert revoked.identity_state == "awaiting_activation_approval"
        assert not expired.activation_decisions
        assert not revoked.activation_decisions


@pytest.mark.anyio
async def test_proposals_create_only_drafts_and_preserve_decisions(
    database: Database,
) -> None:
    canvas_id, _, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(database, workflow_version_id)
    payload = {
        "agentKind": AgentKind.WORKFLOW_ASSISTANT.value,
        "displayName": "Architect proposal",
        "description": "A structured proposal with no authority.",
        "version": definition.model_dump(mode="json"),
    }
    async with database.sessions() as session:
        service = _service(session)
        proposal = await service.create_proposal(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=ProposalKind.AGENT_CREATION,
            source_kind="adaptive_agent_architect",
            payload=payload,
            idempotency_key="architect-proposal-one",
        )
        assert proposal.source_kind == "adaptive_agent_architect"
        decision = await service.decide_proposal(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            proposal_id=proposal.proposal_id,
            decision="accepted",
        )
        assert decision.resulting_agent_id is not None
        created = await service.get_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=decision.resulting_agent_id,
        )
        assert created.identity_state == "draft"
        assert all(state == "draft" for state in created.version_states.values())
        replay = await service.decide_proposal(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            proposal_id=proposal.proposal_id,
            decision="accepted",
        )
        assert replay.decision_id == decision.decision_id
        with pytest.raises(AgentStudioConflictError):
            await service.decide_proposal(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                proposal_id=proposal.proposal_id,
                decision="rejected",
            )
        await session.commit()


@pytest.mark.anyio
async def test_communication_profiles_and_revisions_preserve_scope_and_facts(
    database: Database,
) -> None:
    canvas_id, _, _ = await _active_workflow(database, include_bundle=False)
    async with database.sessions() as session:
        service = _service(session)
        identity, profile = await service.create_communication_profile(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            name="Plain technical",
            profile=CommunicationProfileInput(
                audience=Audience.TECHNICAL,
                reading_level=ReadingLevel.PLAIN,
                formality=Formality.NEUTRAL,
                verbosity=Verbosity.CONCISE,
                technical_depth=TechnicalDepth.HIGH,
                orwell_rules=True,
            ),
            idempotency_key="communication-profile-one",
        )
        assert identity.canvas_id == canvas_id
        assert profile.canvas_id == canvas_id
        original = (
            'Alice Smith wrote "Keep this" on 2026-07-25. '
            "See https://example.com/source and cite-1. "
            "The result has insufficient evidence."
        )
        revised = (
            'Alice Smith wrote "Keep this" on 2026-07-25. '
            "The concise result still has insufficient evidence; "
            "see https://example.com/source and cite-1."
        )
        revision = await service.propose_communication_revision(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            profile_version_id=profile.profile_version_id,
            original_text=original,
            revised_text=revised,
            citation_ids=("cite-1",),
            idempotency_key="communication-revision-one",
        )
        assert revision.preservation_status == "preserved"
        accepted = await service.decide_communication_revision(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            revision_id=revision.revision_id,
            decision="accepted",
        )
        assert accepted.decision == "accepted"

        unsafe = await service.propose_communication_revision(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            profile_version_id=profile.profile_version_id,
            original_text=original,
            revised_text="A shorter unsupported rewrite.",
            citation_ids=("cite-1",),
            idempotency_key="communication-revision-unsafe",
        )
        assert unsafe.preservation_status == "rejected"
        with pytest.raises(AgentStudioAuthorityError):
            await service.decide_communication_revision(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                revision_id=unsafe.revision_id,
                decision="accepted",
            )
        await session.commit()

    async with database.sessions() as session:
        stored = await session.get(
            BoundedCommunicationProfile,
            identity.profile_id,
        )
        assert stored is not None
        assert (
            stored.user_id,
            stored.workspace_id,
            stored.canvas_id,
        ) == (SYSTEM_USER_ID, SYSTEM_WORKSPACE_ID, canvas_id)


@pytest.mark.anyio
async def test_suspension_restore_retirement_and_cross_scope_fail_closed(
    database: Database,
) -> None:
    canvas_id, objects, workflow_version_id, agent_id = await _active_agent(database)
    async with database.sessions() as session:
        service = _service(session)
        suspended = await service.change_lifecycle(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=agent_id,
            operation="suspend",
            reason_code="human_review",
        )
        assert suspended.identity_state == "suspended"
        with pytest.raises(AgentStudioAuthorityError):
            await service.invoke(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                agent_id=agent_id,
                workflow_version_id=workflow_version_id,
                query="First",
                selected_object_ids=(objects["note_one"],),
                seed_object_ids=(objects["note_one"],),
                idempotency_key="suspended-invocation",
            )
        restored = await service.change_lifecycle(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=agent_id,
            operation="restore",
            reason_code="human_restored",
        )
        assert restored.identity_state == "active"
        retired = await service.change_lifecycle(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=agent_id,
            operation="retire",
            reason_code="human_retired",
        )
        assert retired.identity_state == "retired"
        assert retired.versions
        with pytest.raises(AgentStudioAuthorityError):
            await service.invoke(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                agent_id=agent_id,
                workflow_version_id=workflow_version_id,
                query="First",
                selected_object_ids=(objects["note_one"],),
                seed_object_ids=(objects["note_one"],),
                idempotency_key="retired-invocation",
            )
        with pytest.raises(AgentStudioNotFoundError):
            await service.get_agent(
                user_id=SYSTEM_USER_ID,
                workspace_id=uuid.uuid4(),
                canvas_id=canvas_id,
                agent_id=agent_id,
            )
        await session.commit()


@pytest.mark.anyio
async def test_agent_studio_failure_injection_leaves_no_partial_evidence(
    database: Database,
) -> None:
    canvas_id, _, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(database, workflow_version_id)

    async def fail_after_outbox() -> None:
        raise RuntimeError("injected agent event failure")

    async with database.sessions() as session:
        service = _service(session)
        service.events = DomainEventService(session, after_outbox=fail_after_outbox)
        with pytest.raises(RuntimeError, match="injected agent event failure"):
            await service.create_agent(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                kind=AgentKind.WORKFLOW_ASSISTANT,
                display_name="Atomic failure",
                description="Must not persist partially.",
                version=definition,
                idempotency_key="agent-failure-injection",
            )
        await session.rollback()

    async with database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BoundedAgentIdentity)
                .where(BoundedAgentIdentity.idempotency_key == "agent-failure-injection")
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(TraceEvent.operation.like("agent.%"))
            )
            == 0
        )


@pytest.mark.anyio
async def test_agent_events_project_once_to_safe_scoped_activity(
    database: Database,
) -> None:
    canvas_id, _, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(database, workflow_version_id)
    async with database.sessions() as session:
        await _service(session).create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=AgentKind.WORKFLOW_ASSISTANT,
            display_name="Projected agent",
            description="Produces safe activity without exposing its prompt.",
            version=definition,
            idempotency_key="agent-activity-projection",
        )
        await session.commit()

    async with database.sessions() as session:
        outbox = DomainEventOutboxService(session)
        while await outbox.process_one(owner_id="agent-studio-projector") is not None:
            pass
        rows = await DomainEventService(session).list_activity(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            limit=100,
        )
        agent_rows = [row for row in rows if row.event.event_type == "agent.identity.created"]
        assert len(agent_rows) == 1
        assert agent_rows[0].event.canvas_id == canvas_id
        serialized = repr(agent_rows[0]).casefold()
        assert definition.system_instruction.casefold() not in serialized
        assert "grant" not in serialized
        projected_count = await session.scalar(
            select(func.count()).select_from(DomainActivityEntry)
        )
        assert await outbox.process_one(owner_id="agent-studio-projector-replay") is None
        assert (
            await session.scalar(select(func.count()).select_from(DomainActivityEntry))
            == projected_count
        )
        await session.commit()


async def _file_database(path: Path) -> Database:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.sessions() as session:
        session.add(
            User(
                id=SYSTEM_USER_ID,
                email="agent-studio-concurrency@mobius.invalid",
                email_normalized="agent-studio-concurrency@mobius.invalid",
                password_hash="test-only",
                display_name="Agent Studio concurrency",
                email_verified=True,
            )
        )
        session.add(
            Workspace(
                id=SYSTEM_WORKSPACE_ID,
                owner_id=SYSTEM_USER_ID,
                name="Agent Studio concurrency",
            )
        )
        await session.commit()
    return database


@pytest.mark.anyio
async def test_competing_exact_agent_creation_converges_on_one_identity(
    tmp_path: Path,
) -> None:
    database = await _file_database(tmp_path / "agent-studio-concurrency.db")
    try:
        canvas_id, _, workflow_version_id = await _active_workflow(
            database,
            include_bundle=False,
        )
        definition = await _definition(database, workflow_version_id)

        async def create() -> uuid.UUID | AgentStudioStorageError:
            async with database.sessions() as session:
                try:
                    record = await _service(session).create_agent(
                        user_id=SYSTEM_USER_ID,
                        workspace_id=SYSTEM_WORKSPACE_ID,
                        canvas_id=canvas_id,
                        kind=AgentKind.WORKFLOW_ASSISTANT,
                        display_name="Contended identity",
                        description="Exact duplicate delivery converges.",
                        version=definition,
                        idempotency_key="agent-concurrent-identity",
                    )
                    await session.commit()
                    return record.identity.agent_id
                except AgentStudioStorageError as exc:
                    await session.rollback()
                    return exc

        results = await asyncio.gather(create(), create())
        successes = [value for value in results if isinstance(value, uuid.UUID)]
        assert successes
        assert len(set(successes)) == 1

        async with database.sessions() as session:
            replay = await _service(session).create_agent(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                kind=AgentKind.WORKFLOW_ASSISTANT,
                display_name="Contended identity",
                description="Exact duplicate delivery converges.",
                version=definition,
                idempotency_key="agent-concurrent-identity",
            )
            await session.commit()
            assert replay.identity.agent_id == successes[0]
            assert replay.duplicate is True
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(BoundedAgentIdentity)
                    .where(BoundedAgentIdentity.idempotency_key == "agent-concurrent-identity")
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(BoundedAgentVersion)
                    .where(BoundedAgentVersion.agent_id == replay.identity.agent_id)
                )
                == 1
            )
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_agent_studio_api_is_scoped_and_omits_private_prompts(
    database: Database,
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    canvas_id, _, workflow_version_id = await _active_workflow(
        database,
        include_bundle=False,
    )
    definition = await _definition(database, workflow_version_id)
    base = f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/canvases/{canvas_id}/agent-studio"
    registries = await client.get(f"{base}/registries")
    assert registries.status_code == 200
    assert "shell.execute" not in registries.text
    payload = {
        "kind": "grounded_research_assistant",
        "displayName": "API analyst",
        "description": "Safe operational facts only.",
        "version": {
            "schemaVersion": "bounded-agent-definition-v1",
            "purpose": definition.purpose,
            "systemInstruction": definition.system_instruction,
            "workflowVersionIds": [str(workflow_version_id)],
            "capabilityRequirements": [
                {
                    "capability": item.capability.value,
                    "resourceKind": item.resource_kind.value,
                }
                for item in definition.capability_requirements
            ],
            "selectedContextPolicy": "required_explicit",
            "provider": "mock",
            "model": "mock-context-v1",
            "riskClass": "r1_draft",
        },
        "idempotencyKey": "agent-api-create",
    }
    response = await client.post(f"{base}/agents", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["lifecycleState"] == "draft"
    assert "systemInstruction" not in response.text
    assert "grant" not in response.text.casefold()
    assert "chain of thought" not in response.text.casefold()
    assert body["versions"][0]["workflowBindings"][0]["workflowVersionId"] == str(
        workflow_version_id
    )

    rejected = await client.post(
        f"{base}/agents",
        json={
            **payload,
            "idempotencyKey": "agent-api-injection",
            "activationState": "active",
            "grant": {"capability": "shell.execute"},
        },
    )
    assert rejected.status_code == 422
    cross_scope = await client.get(
        f"{api_prefix}/workspaces/{uuid.uuid4()}/canvases/"
        f"{canvas_id}/agent-studio/agents/{body['agentId']}"
    )
    assert cross_scope.status_code == 404


@pytest.mark.anyio
async def test_orm_agent_evidence_is_immutable(database: Database) -> None:
    _, _, _, agent_id = await _active_agent(database)
    async with database.sessions() as session:
        row = await session.scalar(
            select(BoundedAgentVersion).where(BoundedAgentVersion.agent_id == agent_id)
        )
        assert row is not None
        row.purpose = "mutated"
        with pytest.raises((ValueError, StatementError), match="append-only"):
            await session.flush()
        await session.rollback()

    async with database.sessions() as session:
        stored = await session.scalar(
            select(BoundedAgentVersion).where(BoundedAgentVersion.agent_id == agent_id)
        )
        assert stored is not None
        assert stored.purpose != "mutated"
