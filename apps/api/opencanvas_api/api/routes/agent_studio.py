from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, status
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.agent_studio_schemas import (
    AgentActivationDecisionIn,
    AgentActivationRequestIn,
    AgentActivationRequestOut,
    AgentCapabilityRequirementOut,
    AgentCreateIn,
    AgentEvaluationIn,
    AgentEvaluationOut,
    AgentInvocationIn,
    AgentInvocationOut,
    AgentLifecycleIn,
    AgentLimitsIn,
    AgentOut,
    AgentProposalDecisionIn,
    AgentProposalIn,
    AgentProposalOut,
    AgentRegistriesOut,
    AgentValidationOut,
    AgentVersionCreateIn,
    AgentVersionIn,
    AgentVersionOut,
    AgentWorkflowBindingOut,
    CommunicationProfileIn,
    CommunicationProfileOut,
    CommunicationProfileVersionIn,
    CommunicationRevisionDecisionIn,
    CommunicationRevisionIn,
    CommunicationRevisionOut,
)
from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    enforce_ai_rate_limit,
    get_ai_provider,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.serialization import utc
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    BoundedAgentActivationRequest,
    BoundedAgentCapabilityRequirement,
    BoundedAgentEvaluation,
    BoundedAgentInvocation,
    BoundedAgentProposal,
    BoundedAgentProposalDecision,
    BoundedAgentValidationReport,
    BoundedAgentVersion,
    BoundedAgentWorkflowBinding,
    BoundedCommunicationProfile,
    BoundedCommunicationProfileVersion,
    BoundedCommunicationRevision,
    ControlledWorkflowExecution,
)
from opencanvas_api.services.agent_studio import (
    AGENT_REGISTRY_VERSION,
    AgentKind,
    AgentLifecycle,
    AgentLimits,
    AgentRecord,
    AgentStudioAuthorityError,
    AgentStudioConflictError,
    AgentStudioError,
    AgentStudioNotFoundError,
    AgentStudioStorageError,
    AgentStudioValidationError,
    AgentVersionInput,
    AgentVersionLifecycle,
    Audience,
    BoundedAgentStudioService,
    CapabilityRequirementInput,
    CommunicationPolicyInput,
    CommunicationProfileInput,
    EvaluationOutcome,
    Formality,
    ProposalKind,
    ReadingLevel,
    TechnicalDepth,
    ValidationOutcome,
    Verbosity,
)
from opencanvas_api.services.agents.contracts import Capability, ResourceKind, RiskClass
from opencanvas_api.services.ai import AIProvider
from opencanvas_api.services.documents.embeddings import build_embedding_provider
from opencanvas_api.services.workflows import ControlledWorkflowService, WorkflowError

router = APIRouter(prefix="/workspaces/{workspace_id}/canvases/{canvas_id}/agent-studio")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _error(error: AgentStudioError | WorkflowError) -> ApiError:
    if isinstance(error, AgentStudioNotFoundError):
        return ApiError(status.HTTP_404_NOT_FOUND, error.code, error.safe_message)
    if isinstance(error, AgentStudioConflictError):
        return ApiError(status.HTTP_409_CONFLICT, error.code, error.safe_message)
    if isinstance(error, AgentStudioValidationError):
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            error.code,
            error.safe_message,
        )
    if isinstance(error, AgentStudioAuthorityError):
        return ApiError(status.HTTP_403_FORBIDDEN, error.code, error.safe_message)
    if isinstance(error, AgentStudioStorageError):
        return ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error.code,
            error.safe_message,
        )
    if isinstance(error, WorkflowError):
        return ApiError(status.HTTP_403_FORBIDDEN, error.code, error.safe_message)
    return ApiError(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        error.code,
        error.safe_message,
    )


def _service(
    session: AsyncSession,
    provider: AIProvider,
    settings: Settings,
) -> BoundedAgentStudioService:
    workflow = ControlledWorkflowService(
        session,
        embedding_provider=build_embedding_provider(settings),
        ai_provider=provider,
    )
    return BoundedAgentStudioService(session, workflow_service=workflow)


def _version_input(value: AgentVersionIn) -> AgentVersionInput:
    return AgentVersionInput(
        schema_version=value.schema_version,
        purpose=value.purpose,
        system_instruction=value.system_instruction,
        workflow_version_ids=tuple(value.workflow_version_ids),
        capability_requirements=tuple(
            CapabilityRequirementInput(
                capability=item.capability,
                resource_kind=item.resource_kind,
            )
            for item in value.capability_requirements
        ),
        selected_context_policy=value.selected_context_policy,
        provider=value.provider,
        model=value.model,
        limits=AgentLimits.model_validate(value.limits.model_dump()),
        communication_policy=CommunicationPolicyInput.model_validate(
            value.communication_policy.model_dump()
        ),
        evaluation_policy=value.evaluation_policy,
        risk_class=value.risk_class,
    )


def _profile_input(
    value: CommunicationProfileIn | CommunicationProfileVersionIn,
) -> CommunicationProfileInput:
    return CommunicationProfileInput(
        audience=value.audience,
        reading_level=value.reading_level,
        formality=value.formality,
        verbosity=value.verbosity,
        technical_depth=value.technical_depth,
        orwell_rules=value.orwell_rules,
    )


@router.get("/registries", response_model=AgentRegistriesOut)
async def get_agent_registries(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentRegistriesOut:
    try:
        await _service(session, provider, settings).list_agents(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            limit=1,
        )
    except AgentStudioError as exc:
        raise _error(exc) from exc
    return AgentRegistriesOut(
        registry_version=AGENT_REGISTRY_VERSION,
        agent_kinds=[item.value for item in AgentKind],
        agent_lifecycles=[item.value for item in AgentLifecycle],
        agent_version_lifecycles=[item.value for item in AgentVersionLifecycle],
        proposal_kinds=[item.value for item in ProposalKind],
        validation_outcomes=[item.value for item in ValidationOutcome],
        evaluation_outcomes=[item.value for item in EvaluationOutcome],
        capabilities=[item.value for item in Capability],
        resource_kinds=[item.value for item in ResourceKind],
        risk_classes=[item.value for item in RiskClass if item is not RiskClass.R4_PROHIBITED],
        providers={
            "mock": ["mock-context-v1"],
            "openai": ["gpt-5.6-terra"],
        },
        communication={
            "audiences": [item.value for item in Audience],
            "readingLevels": [item.value for item in ReadingLevel],
            "formalities": [item.value for item in Formality],
            "verbosities": [item.value for item in Verbosity],
            "technicalDepths": [item.value for item in TechnicalDepth],
        },
        server_maximums=AgentLimitsIn(
            max_workflow_executions=8,
            max_model_calls=16,
            max_retrieval_calls=16,
            max_effects=4,
            max_approvals=8,
            max_retries=3,
            max_duration_seconds=900,
            max_input_chars=60_000,
            max_output_chars=40_000,
            max_evidence_bundle_requests=4,
        ),
    )


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: AgentCreateIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentOut:
    service = _service(session, provider, settings)
    try:
        record = await service.create_agent(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            kind=payload.kind,
            display_name=payload.display_name,
            description=payload.description,
            version=_version_input(payload.version),
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except (AgentStudioError, WorkflowError) as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _agent_out(session, record)


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
    lifecycle: AgentLifecycle | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[AgentOut]:
    try:
        records = await _service(session, provider, settings).list_agents(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            lifecycle=lifecycle,
            limit=limit,
            offset=offset,
        )
    except AgentStudioError as exc:
        raise _error(exc) from exc
    return [await _agent_out(session, item) for item in records]


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    agent_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentOut:
    try:
        record = await _service(session, provider, settings).get_agent(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            agent_id=agent_id,
        )
    except AgentStudioError as exc:
        raise _error(exc) from exc
    return await _agent_out(session, record)


@router.post("/agents/{agent_id}/versions", response_model=AgentOut)
async def create_agent_version(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentVersionCreateIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentOut:
    service = _service(session, provider, settings)
    try:
        record = await service.create_version(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            agent_id=agent_id,
            version=_version_input(payload.version),
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _agent_out(session, record)


@router.post("/versions/{version_id}/validate", response_model=AgentValidationOut)
async def validate_agent_version(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    version_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentValidationOut:
    service = _service(session, provider, settings)
    try:
        report = await service.validate_version(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            version_id=version_id,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _validation_out(report)


@router.post(
    "/versions/{version_id}/activation-requests",
    response_model=AgentActivationRequestOut,
)
async def request_agent_activation(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: AgentActivationRequestIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentActivationRequestOut:
    service = _service(session, provider, settings)
    try:
        row = await service.request_activation(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            version_id=version_id,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _activation_out(row, None)


@router.post(
    "/activation-requests/{activation_request_id}/decision",
    response_model=AgentActivationRequestOut,
)
async def decide_agent_activation(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    activation_request_id: uuid.UUID,
    payload: AgentActivationDecisionIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentActivationRequestOut:
    service = _service(session, provider, settings)
    session_id = principal.session_id or uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"opencanvas:test-agent-activation-session:{principal.user_id}",
    )
    try:
        decision = await service.decide_activation(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            activation_request_id=activation_request_id,
            decision=payload.decision,
            session_id=session_id,
        )
        request = await session.get(
            BoundedAgentActivationRequest,
            activation_request_id,
        )
        if request is None:
            raise AgentStudioNotFoundError()
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _activation_out(request, decision.decision)


@router.post(
    "/agents/{agent_id}/invocations",
    response_model=AgentInvocationOut,
)
async def invoke_agent(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentInvocationIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(enforce_ai_rate_limit)],
) -> AgentInvocationOut:
    service = _service(session, provider, settings)
    try:
        invocation, workflow = await service.invoke(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            agent_id=agent_id,
            workflow_version_id=payload.workflow_version_id,
            query=payload.query,
            selected_object_ids=tuple(payload.selected_object_ids),
            seed_object_ids=tuple(payload.seed_object_ids),
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except (AgentStudioError, WorkflowError) as exc:
        await session.rollback()
        raise _error(exc) from exc
    return AgentInvocationOut(
        invocation_id=invocation.invocation_id,
        agent_id=invocation.agent_id,
        agent_version_id=invocation.agent_version_id,
        workflow_version_id=invocation.workflow_version_id,
        workflow_execution_id=invocation.workflow_execution_id,
        workflow_status=workflow.execution.status,
        workflow_outcome=workflow.execution.outcome,
        graph_revision=invocation.graph_revision,
        trace_id=invocation.trace_id,
        created_at=utc(invocation.created_at),
        duplicate=workflow.duplicate,
    )


@router.post(
    "/invocations/{invocation_id}/evaluations",
    response_model=AgentEvaluationOut,
)
async def evaluate_agent_invocation(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    invocation_id: uuid.UUID,
    payload: AgentEvaluationIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentEvaluationOut:
    service = _service(session, provider, settings)
    try:
        row = await service.evaluate(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            invocation_id=invocation_id,
            outcome=payload.outcome,
            summary=payload.summary,
            recommendations=cast(list[dict[str, object]], payload.recommendations),
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _evaluation_out(row)


@router.post("/proposals", response_model=AgentProposalOut)
async def create_agent_proposal(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: AgentProposalIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentProposalOut:
    service = _service(session, provider, settings)
    try:
        row = await service.create_proposal(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            kind=payload.kind,
            source_kind=payload.source_kind,
            payload=cast(dict[str, object], payload.payload),
            idempotency_key=payload.idempotency_key,
            agent_id=payload.agent_id,
            source_invocation_id=payload.source_invocation_id,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _proposal_out(row, None)


@router.post("/proposals/{proposal_id}/decision", response_model=AgentProposalOut)
async def decide_agent_proposal(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: AgentProposalDecisionIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentProposalOut:
    service = _service(session, provider, settings)
    try:
        decision = await service.decide_proposal(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            proposal_id=proposal_id,
            decision=payload.decision,
        )
        proposal = await session.get(BoundedAgentProposal, proposal_id)
        if proposal is None:
            raise AgentStudioNotFoundError()
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _proposal_out(proposal, decision)


@router.post("/communication-profiles", response_model=CommunicationProfileOut)
async def create_communication_profile(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: CommunicationProfileIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> CommunicationProfileOut:
    service = _service(session, provider, settings)
    try:
        identity, version = await service.create_communication_profile(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            name=payload.name,
            profile=_profile_input(payload),
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _profile_out(identity, version)


@router.get("/communication-profiles", response_model=list[CommunicationProfileOut])
async def list_communication_profiles(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> list[CommunicationProfileOut]:
    try:
        await _service(session, provider, settings).list_agents(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            limit=1,
        )
    except AgentStudioError as exc:
        raise _error(exc) from exc
    identities = (
        await session.scalars(
            select(BoundedCommunicationProfile)
            .where(
                BoundedCommunicationProfile.user_id == principal.user_id,
                BoundedCommunicationProfile.workspace_id == workspace_id,
                BoundedCommunicationProfile.canvas_id == canvas_id,
            )
            .order_by(BoundedCommunicationProfile.created_at)
        )
    ).all()
    results: list[CommunicationProfileOut] = []
    for identity in identities:
        version = await session.scalar(
            select(BoundedCommunicationProfileVersion)
            .where(BoundedCommunicationProfileVersion.profile_id == identity.profile_id)
            .order_by(BoundedCommunicationProfileVersion.version_number.desc())
            .limit(1)
        )
        if version is not None:
            results.append(_profile_out(identity, version))
    return results


@router.post(
    "/communication-profiles/{profile_id}/versions",
    response_model=CommunicationProfileOut,
)
async def create_communication_profile_version(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    profile_id: uuid.UUID,
    payload: CommunicationProfileVersionIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> CommunicationProfileOut:
    service = _service(session, provider, settings)
    try:
        version = await service.create_profile_version(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            profile_id=profile_id,
            profile=_profile_input(payload),
            idempotency_key=payload.idempotency_key,
        )
        identity = await session.get(BoundedCommunicationProfile, profile_id)
        if identity is None:
            raise AgentStudioNotFoundError()
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _profile_out(identity, version)


@router.post("/communication-revisions", response_model=CommunicationRevisionOut)
async def propose_communication_revision(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: CommunicationRevisionIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> CommunicationRevisionOut:
    service = _service(session, provider, settings)
    try:
        row = await service.propose_communication_revision(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            profile_version_id=payload.profile_version_id,
            original_text=payload.original_text,
            revised_text=payload.revised_text,
            citation_ids=tuple(payload.citation_ids),
            idempotency_key=payload.idempotency_key,
            source_invocation_id=payload.source_invocation_id,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _revision_out(row, None)


@router.post(
    "/communication-revisions/{revision_id}/decision",
    response_model=CommunicationRevisionOut,
)
async def decide_communication_revision(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    revision_id: uuid.UUID,
    payload: CommunicationRevisionDecisionIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> CommunicationRevisionOut:
    service = _service(session, provider, settings)
    try:
        decision = await service.decide_communication_revision(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            revision_id=revision_id,
            decision=payload.decision,
        )
        row = await session.get(BoundedCommunicationRevision, revision_id)
        if row is None:
            raise AgentStudioNotFoundError()
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return _revision_out(row, decision.decision)


@router.post("/agents/{agent_id}/lifecycle", response_model=AgentOut)
async def change_agent_lifecycle(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentLifecycleIn,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> AgentOut:
    service = _service(session, provider, settings)
    try:
        record = await service.change_lifecycle(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            agent_id=agent_id,
            operation=payload.operation,
            reason_code=payload.reason_code,
        )
        await session.commit()
    except AgentStudioError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _agent_out(session, record)


async def _agent_out(session: AsyncSession, record: AgentRecord) -> AgentOut:
    decision_by_request = {
        item.activation_request_id: item.decision for item in record.activation_decisions
    }
    versions = [
        await _version_out(
            session,
            item,
            record.version_states[item.version_id],
            include_private_governance=not record.shared_inspection,
        )
        for item in record.versions
    ]
    executions = {
        item.execution_id: item
        for item in (
            await session.scalars(
                select(ControlledWorkflowExecution).where(
                    ControlledWorkflowExecution.execution_id.in_(
                        [value.workflow_execution_id for value in record.invocations]
                    )
                )
            )
        ).all()
    }
    proposal_ids = [item.proposal_id for item in record.proposals]
    proposal_decisions = (
        {
            item.proposal_id: item
            for item in (
                await session.scalars(
                    select(BoundedAgentProposalDecision).where(
                        BoundedAgentProposalDecision.proposal_id.in_(proposal_ids)
                    )
                )
            ).all()
        }
        if proposal_ids
        else {}
    )
    return AgentOut(
        agent_id=record.identity.agent_id,
        workspace_id=record.identity.workspace_id,
        canvas_id=record.identity.canvas_id,
        kind=record.identity.kind,
        display_name=record.identity.display_name,
        description=record.identity.description,
        lifecycle_state=record.identity_state,
        trace_id=record.identity.trace_id,
        created_at=utc(record.identity.created_at),
        versions=versions,
        validations=[_validation_out(item) for item in record.validations],
        activation_requests=[
            _activation_out(
                item,
                cast(
                    Literal["approved", "denied"] | None,
                    decision_by_request.get(item.activation_request_id),
                ),
            )
            for item in record.activation_requests
        ],
        invocations=[
            _invocation_out(item, executions.get(item.workflow_execution_id))
            for item in record.invocations
        ],
        evaluations=[_evaluation_out(item) for item in record.evaluations],
        proposals=[
            _proposal_out(item, proposal_decisions.get(item.proposal_id))
            for item in record.proposals
        ],
        duplicate=record.duplicate,
    )


async def _version_out(
    session: AsyncSession,
    row: BoundedAgentVersion,
    lifecycle: str,
    *,
    include_private_governance: bool = True,
) -> AgentVersionOut:
    bindings = (
        (
            await session.scalars(
                select(BoundedAgentWorkflowBinding)
                .where(BoundedAgentWorkflowBinding.agent_version_id == row.version_id)
                .order_by(BoundedAgentWorkflowBinding.ordinal)
            )
        ).all()
        if include_private_governance
        else ()
    )
    requirements = (
        (
            await session.scalars(
                select(BoundedAgentCapabilityRequirement)
                .where(BoundedAgentCapabilityRequirement.agent_version_id == row.version_id)
                .order_by(
                    BoundedAgentCapabilityRequirement.capability,
                    BoundedAgentCapabilityRequirement.resource_kind,
                )
            )
        ).all()
        if include_private_governance
        else ()
    )
    return AgentVersionOut(
        version_id=row.version_id,
        version_number=row.version_number,
        lifecycle_state=lifecycle,
        schema_version=row.schema_version,
        purpose=row.purpose,
        prompt_template_version=row.prompt_template_version,
        selected_context_policy=row.selected_context_policy,
        provider=row.provider,
        model=row.model,
        limits=cast(dict[str, JsonValue], row.limits),
        communication_policy=cast(dict[str, JsonValue], row.communication_policy),
        evaluation_policy=row.evaluation_policy,
        risk_class=row.risk_class,
        content_digest=row.content_digest,
        supersedes_version_id=row.supersedes_version_id,
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
        workflow_bindings=[
            AgentWorkflowBindingOut(
                workflow_version_id=item.workflow_version_id,
                workflow_digest=item.workflow_digest,
                ordinal=item.ordinal,
            )
            for item in bindings
        ],
        capability_requirements=[
            AgentCapabilityRequirementOut(
                capability=item.capability,
                resource_kind=item.resource_kind,
            )
            for item in requirements
        ],
    )


def _validation_out(row: BoundedAgentValidationReport) -> AgentValidationOut:
    return AgentValidationOut(
        validation_id=row.validation_id,
        agent_version_id=row.agent_version_id,
        content_digest=row.content_digest,
        outcome=row.outcome,
        issues=cast(list[dict[str, JsonValue]], row.issues),
        registry_versions=cast(dict[str, JsonValue], row.registry_versions),
        validator_version=row.validator_version,
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
    )


def _activation_out(
    row: BoundedAgentActivationRequest,
    decision: str | None,
) -> AgentActivationRequestOut:
    return AgentActivationRequestOut(
        activation_request_id=row.activation_request_id,
        agent_version_id=row.agent_version_id,
        validation_id=row.validation_id,
        request_digest=row.request_digest,
        authority_summary=cast(dict[str, JsonValue], row.authority_summary),
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
        expires_at=utc(row.expires_at),
        decision=cast(Literal["approved", "denied"] | None, decision),
    )


def _invocation_out(
    row: BoundedAgentInvocation,
    execution: ControlledWorkflowExecution | None,
) -> AgentInvocationOut:
    return AgentInvocationOut(
        invocation_id=row.invocation_id,
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        workflow_version_id=row.workflow_version_id,
        workflow_execution_id=row.workflow_execution_id,
        workflow_status=execution.status if execution is not None else "unavailable",
        workflow_outcome=execution.outcome if execution is not None else None,
        graph_revision=row.graph_revision,
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
    )


def _evaluation_out(row: BoundedAgentEvaluation) -> AgentEvaluationOut:
    return AgentEvaluationOut(
        evaluation_id=row.evaluation_id,
        invocation_id=row.invocation_id,
        outcome=row.outcome,
        evidence_digest=row.evidence_digest,
        summary=row.summary,
        recommendations=cast(list[dict[str, JsonValue]], row.recommendations),
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
    )


def _proposal_out(
    row: BoundedAgentProposal,
    decision: BoundedAgentProposalDecision | None,
) -> AgentProposalOut:
    return AgentProposalOut(
        proposal_id=row.proposal_id,
        kind=row.kind,
        source_kind=row.source_kind,
        agent_id=row.agent_id,
        source_invocation_id=row.source_invocation_id,
        payload=cast(dict[str, JsonValue], row.payload),
        payload_digest=row.payload_digest,
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
        decision=(
            cast(Literal["accepted", "rejected"], decision.decision)
            if decision is not None
            else None
        ),
        resulting_agent_id=(decision.resulting_agent_id if decision is not None else None),
        resulting_version_id=(decision.resulting_version_id if decision is not None else None),
    )


def _profile_out(
    identity: BoundedCommunicationProfile,
    row: BoundedCommunicationProfileVersion,
) -> CommunicationProfileOut:
    return CommunicationProfileOut(
        profile_id=identity.profile_id,
        profile_version_id=row.profile_version_id,
        workspace_id=identity.workspace_id,
        canvas_id=identity.canvas_id,
        version_number=row.version_number,
        name=identity.name,
        audience=row.audience,
        reading_level=row.reading_level,
        formality=row.formality,
        verbosity=row.verbosity,
        technical_depth=row.technical_depth,
        orwell_rules=row.orwell_rules,
        content_digest=row.content_digest,
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
    )


def _revision_out(
    row: BoundedCommunicationRevision,
    decision: str | None,
) -> CommunicationRevisionOut:
    return CommunicationRevisionOut(
        revision_id=row.revision_id,
        profile_version_id=row.profile_version_id,
        source_invocation_id=row.source_invocation_id,
        original_text=row.original_text,
        revised_text=row.revised_text,
        original_digest=row.original_digest,
        revised_digest=row.revised_digest,
        protected_facts_digest=row.protected_facts_digest,
        preservation_status=row.preservation_status,
        safe_failure_code=row.safe_failure_code,
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
        decision=cast(Literal["accepted", "rejected"] | None, decision),
    )
