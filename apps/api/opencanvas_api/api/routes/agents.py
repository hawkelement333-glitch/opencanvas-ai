from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.agent_schemas import (
    AgentApprovalConsumptionOut,
    AgentApprovalOut,
    AgentAuditAttributeOut,
    AgentAuditEventOut,
    AgentContextReferenceOut,
    AgentDraftCitationOut,
    AgentDraftOut,
    AgentDraftPreparedOut,
    AgentDraftStart,
    AgentExecutionCancel,
    AgentExecutionCancelOut,
    AgentExecutionInspectionOut,
    AgentGrantOut,
    AgentPlanReferenceOut,
    AgentPolicyDecisionOut,
    AgentRevocationOut,
    AgentStateOut,
    ReversibleWriteApprovalOut,
    ReversibleWriteApprovalStart,
    ReversibleWriteEffectOut,
    ReversibleWriteEffectStart,
    ReversibleWriteProposalOut,
    ReversibleWriteProposalStart,
    ReversibleWriteRollbackApprovalOut,
    ReversibleWriteRollbackApprovalStart,
    ReversibleWriteRollbackOut,
    ReversibleWriteRollbackReviewOut,
    ReversibleWriteRollbackStart,
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
from opencanvas_api.services.agents.contracts import contract_digest
from opencanvas_api.services.agents.execution import (
    CancellationRequest,
    ControlledExecutionLifecycle,
)
from opencanvas_api.services.agents.grounded_draft import (
    ControlledDraftError,
    ControlledDraftResult,
    ControlledGroundedDraftService,
)
from opencanvas_api.services.agents.persistence import (
    AgentInspection,
    AgentPersistenceNotFound,
    ControlledAgentRepository,
)
from opencanvas_api.services.agents.reversible_write_effects import (
    ReversibleEffectError,
    ReversibleWriteEffectService,
)
from opencanvas_api.services.agents.reversible_write_proposals import (
    ReversibleProposalError,
    ReversibleWriteProposalService,
)
from opencanvas_api.services.agents.reversible_write_rollback_approvals import (
    ReversibleWriteRollbackApprovalService,
    RollbackApprovalError,
)
from opencanvas_api.services.agents.reversible_write_rollback_review import (
    ReversibleWriteRollbackReviewService,
)
from opencanvas_api.services.agents.reversible_write_rollbacks import (
    ReversibleWriteRollbackService,
    RollbackExecutionError,
)
from opencanvas_api.services.agents.reversible_writes import ReversibleWriteAction
from opencanvas_api.services.ai import AIProvider

router = APIRouter(prefix="/workspaces/{workspace_id}/agent-executions")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/reversible-proposals",
    response_model=ReversibleWriteProposalOut,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_reversible_write_proposal(
    workspace_id: uuid.UUID,
    payload: ReversibleWriteProposalStart,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ReversibleWriteProposalOut:
    service = ReversibleWriteProposalService(session)
    try:
        prepared = await service.prepare(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=payload.canvas_id,
            action=ReversibleWriteAction(payload.action),
            title=payload.title,
            text=payload.text,
            note_id=payload.note_id,
            expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except ReversibleProposalError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    proposal = prepared.proposal
    return ReversibleWriteProposalOut(
        execution_id=proposal.execution_id,
        proposal_id=proposal.proposal_id,
        trace_id=prepared.trace_id,
        action=proposal.action.value,
        plan_digest=contract_digest(proposal),
        canvas_id=proposal.canvas.resource_id,
        canvas_revision=proposal.canvas.version or 0,
        note_id=proposal.resource.resource_id if proposal.resource is not None else None,
        expected_revision=proposal.resource.version if proposal.resource is not None else None,
        title=proposal.preview.title,
        text=proposal.preview.text,
        expires_at=proposal.expires_at,
        duplicate=prepared.duplicate,
    )


@router.post(
    "/{execution_id}/reversible-proposal/approve", response_model=ReversibleWriteApprovalOut
)
async def approve_reversible_write_proposal(
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    payload: ReversibleWriteApprovalStart,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ReversibleWriteApprovalOut:
    session_id = principal.session_id or uuid.uuid5(
        uuid.NAMESPACE_URL, f"opencanvas:test-approval-session:{principal.user_id}"
    )
    service = ReversibleWriteProposalService(session)
    try:
        prepared, duplicate = await service.approve(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            presented_plan_digest=payload.plan_digest,
            session_id=session_id,
        )
        await session.commit()
    except ReversibleProposalError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    return ReversibleWriteApprovalOut(
        execution_id=execution_id,
        approval_id=prepared.approval_id,
        plan_digest=contract_digest(prepared.proposal),
        status="ready",
        duplicate=duplicate,
    )


@router.post("/{execution_id}/reversible-effect", response_model=ReversibleWriteEffectOut)
async def apply_reversible_write_effect(
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    payload: ReversibleWriteEffectStart,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ReversibleWriteEffectOut:
    try:
        applied = await ReversibleWriteEffectService(session).apply(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except ReversibleEffectError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    effect = applied.effect
    return ReversibleWriteEffectOut(
        effect_id=effect.effect_id,
        trace_id=effect.trace_id,
        action=effect.action,
        note_id=effect.resulting_resource_id,
        revision=effect.resulting_revision,
        duplicate=applied.duplicate,
    )


@router.get(
    "/canvases/{canvas_id}/reversible-effects/{effect_id}/rollback-review",
    response_model=ReversibleWriteRollbackReviewOut,
)
async def review_reversible_write_rollback(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    effect_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> ReversibleWriteRollbackReviewOut:
    """Read authority from server records; this endpoint never issues or executes rollback."""

    review = await ReversibleWriteRollbackReviewService(session).review(
        authenticated_user_id=principal.user_id,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
        effect_id=effect_id,
    )
    return ReversibleWriteRollbackReviewOut(
        effect_id=review.effect_id,
        forward_action=review.forward_action,
        note_id=review.note_id,
        effect_revision=review.effect_revision,
        current_revision=review.current_revision,
        rollback_action=review.rollback_action,
        rollback_target_kind=review.rollback_target_kind,
        required_capability=review.required_capability,
        eligible=review.eligible,
        approval_required=review.approval_required,
        denial_reason=review.denial_reason,
        conflict=review.conflict,
    )


@router.post(
    "/canvases/{canvas_id}/reversible-effects/{effect_id}/rollback-approval",
    response_model=ReversibleWriteRollbackApprovalOut,
)
async def issue_reversible_write_rollback_approval(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    effect_id: uuid.UUID,
    payload: ReversibleWriteRollbackApprovalStart,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ReversibleWriteRollbackApprovalOut:
    try:
        issued = await ReversibleWriteRollbackApprovalService(session).issue(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            effect_id=effect_id,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except RollbackApprovalError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    approval = issued.approval
    return ReversibleWriteRollbackApprovalOut(
        rollback_approval_id=approval.rollback_approval_id,
        effect_id=approval.effect_id,
        note_id=approval.note_id,
        forward_action=approval.forward_action,
        rollback_action=approval.rollback_action,
        expected_current_revision=approval.expected_current_revision,
        rollback_target_kind=approval.rollback_target_kind,
        expires_at=approval.expires_at,
        duplicate=issued.duplicate,
    )


@router.post(
    "/canvases/{canvas_id}/reversible-effects/{effect_id}/"
    "rollback-approvals/{rollback_approval_id}/execute",
    response_model=ReversibleWriteRollbackOut,
)
async def execute_reversible_write_rollback(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    effect_id: uuid.UUID,
    rollback_approval_id: uuid.UUID,
    payload: ReversibleWriteRollbackStart,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ReversibleWriteRollbackOut:
    try:
        applied = await ReversibleWriteRollbackService(session).apply(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            effect_id=effect_id,
            rollback_approval_id=rollback_approval_id,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except RollbackExecutionError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    result = applied.result
    return ReversibleWriteRollbackOut(
        rollback_result_id=result.rollback_result_id,
        rollback_approval_id=result.rollback_approval_id,
        effect_id=result.effect_id,
        note_id=result.note_id,
        rollback_action=result.rollback_action,
        rollback_target_kind=result.rollback_target_kind,
        resulting_revision=result.resulting_revision,
        created_at=utc(result.created_at),
        duplicate=applied.duplicate,
    )


@router.post("/drafts", response_model=AgentDraftOut, status_code=status.HTTP_201_CREATED)
async def start_grounded_draft(
    workspace_id: uuid.UUID,
    payload: AgentDraftStart,
    request: Request,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(enforce_ai_rate_limit)],
) -> AgentDraftOut:
    service = ControlledGroundedDraftService(session, provider=provider, settings=settings)
    correlation_id = str(getattr(request.state, "correlation_id", uuid.uuid4().hex))
    try:
        prepared = await service.prepare(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=payload.canvas_id,
            selected_node_ids=payload.selected_node_ids,
            instruction=payload.instruction,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            client_request_id=payload.client_request_id,
        )
        result = await service.execute(
            authenticated_user_id=principal.user_id,
            request=prepared.request,
        )
    except ControlledDraftError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    return _draft_out(result)


@router.post(
    "/drafts/prepare", response_model=AgentDraftPreparedOut, status_code=status.HTTP_201_CREATED
)
async def prepare_grounded_draft(
    workspace_id: uuid.UUID,
    payload: AgentDraftStart,
    request: Request,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> AgentDraftPreparedOut:
    service = ControlledGroundedDraftService(
        session, provider=get_ai_provider(settings), settings=settings
    )
    correlation_id = str(getattr(request.state, "correlation_id", uuid.uuid4().hex))
    try:
        prepared = await service.prepare(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=payload.canvas_id,
            selected_node_ids=payload.selected_node_ids,
            instruction=payload.instruction,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            client_request_id=payload.client_request_id,
        )
        await session.commit()
    except ControlledDraftError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    return AgentDraftPreparedOut(
        execution_id=prepared.request.execution_id, status="ready", duplicate=not prepared.created
    )


@router.post("/{execution_id}/run", response_model=AgentDraftOut)
async def run_grounded_draft(
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    request: Request,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(enforce_ai_rate_limit)],
) -> AgentDraftOut:
    service = ControlledGroundedDraftService(session, provider=provider, settings=settings)
    correlation_id = str(getattr(request.state, "correlation_id", uuid.uuid4().hex))
    try:
        prepared = await service.load_prepared_request(
            authenticated_user_id=principal.user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            correlation_id=correlation_id,
        )
        result = await service.execute(authenticated_user_id=principal.user_id, request=prepared)
    except ControlledDraftError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    return _draft_out(result)


@router.post("/{execution_id}/cancel", response_model=AgentExecutionCancelOut)
async def cancel_agent_execution(
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    payload: AgentExecutionCancel,
    request: Request,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> AgentExecutionCancelOut:
    cancellation_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"opencanvas:controlled-draft-cancel:{principal.user_id}:{workspace_id}:"
        f"{execution_id}:{payload.idempotency_key}",
    )
    try:
        outcome = await ControlledExecutionLifecycle(session).cancel(
            authenticated_user_id=principal.user_id,
            request=CancellationRequest(
                cancellation_id=cancellation_id,
                execution_id=execution_id,
                user_id=principal.user_id,
                workspace_id=workspace_id,
                requested_at=datetime.now(UTC),
            ),
            trace_id=uuid.uuid4(),
        )
        await session.commit()
    except AgentPersistenceNotFound as exc:
        raise ApiError(
            http_status.HTTP_404_NOT_FOUND,
            "agent_execution_not_found",
            "Controlled-agent execution not found.",
        ) from exc
    return AgentExecutionCancelOut(
        execution_id=execution_id,
        cancelled=outcome.cancelled,
        duplicate=outcome.duplicate,
        status=outcome.status.value,
        reason_code=outcome.reason_code,
    )


@router.get("/{execution_id}", response_model=AgentExecutionInspectionOut)
async def inspect_agent_execution(
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> AgentExecutionInspectionOut:
    try:
        inspection = await ControlledAgentRepository(session).inspect_execution(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            limit=limit,
            offset=offset,
        )
    except AgentPersistenceNotFound as exc:
        raise ApiError(
            http_status.HTTP_404_NOT_FOUND,
            "agent_execution_not_found",
            "Controlled-agent execution not found.",
        ) from exc
    return _inspection_out(inspection)


def _inspection_out(inspection: AgentInspection) -> AgentExecutionInspectionOut:
    execution = inspection.execution
    return AgentExecutionInspectionOut(
        execution_id=execution.id,
        user_id=execution.user_id,
        workspace_id=execution.workspace_id,
        schema_version=execution.schema_version,
        role=execution.role,
        created_at=utc(execution.created_at),
        context=AgentContextReferenceOut(
            snapshot_id=inspection.context.snapshot_id,
            digest=inspection.context.payload_digest,
            captured_at=utc(inspection.context.captured_at),
        ),
        plan=AgentPlanReferenceOut(
            plan_id=inspection.plan.plan_id,
            digest=inspection.plan.payload_digest,
            created_at=utc(inspection.plan.created_at),
        ),
        states=tuple(
            AgentStateOut(
                state_id=row.state_id,
                status=row.status,
                recorded_at=utc(row.recorded_at),
                safe_reason_code=row.safe_reason_code,
            )
            for row in inspection.states
        ),
        grants=tuple(
            AgentGrantOut(
                grant_id=row.grant_id,
                policy_version=row.policy_version,
                role=row.role,
                context_digest=row.context_digest,
                plan_digest=row.plan_digest,
                issued_at=utc(row.issued_at),
                expires_at=utc(row.expires_at),
                approval_required=row.approval_required,
                approval_id=row.approval_id,
            )
            for row in inspection.grants
        ),
        revocations=tuple(
            AgentRevocationOut(
                revocation_id=row.revocation_id,
                grant_id=row.grant_id,
                revoked_at=utc(row.revoked_at),
                reason_code=row.reason_code,
            )
            for row in inspection.revocations
        ),
        approvals=tuple(
            AgentApprovalOut(
                approval_id=row.approval_id,
                grant_id=row.grant_id,
                policy_version=row.policy_version,
                decision=row.decision,
                context_digest=row.context_digest,
                plan_digest=row.plan_digest,
                decided_at=utc(row.decided_at),
                expires_at=utc(row.expires_at),
            )
            for row in inspection.approvals
        ),
        consumptions=tuple(
            AgentApprovalConsumptionOut(
                consumption_id=row.consumption_id,
                approval_id=row.approval_id,
                policy_decision_id=row.policy_decision_id,
                consumed_at=utc(row.consumed_at),
            )
            for row in inspection.consumptions
        ),
        policy_decisions=tuple(
            AgentPolicyDecisionOut(
                decision_id=row.decision_id,
                policy_version=row.policy_version,
                outcome=row.outcome,
                reason_code=row.reason_code,
                evaluated_at=utc(row.evaluated_at),
                grant_id=row.grant_id,
                approval_id=row.approval_id,
                context_digest=row.context_digest,
                plan_digest=row.plan_digest,
            )
            for row in inspection.policy_decisions
        ),
        audit_events=tuple(
            AgentAuditEventOut(
                event_id=row.event_id,
                trace_id=row.trace_id,
                event_type=row.event_type,
                recorded_at=utc(row.recorded_at),
                attributes=tuple(
                    AgentAuditAttributeOut.model_validate(item) for item in row.attributes
                ),
            )
            for row in inspection.audit_events
        ),
    )


def _draft_out(result: ControlledDraftResult) -> AgentDraftOut:
    return AgentDraftOut(
        execution_id=result.execution_id,
        trace_id=result.trace_id,
        response_id=result.response_id,
        text=result.text,
        insufficient_evidence=result.insufficient_evidence,
        citations=tuple(
            AgentDraftCitationOut(
                source_id=citation.source_id,
                document_id=citation.document_id,
                document_version=citation.document_version,
                chunk_id=citation.chunk_id,
                claim=citation.claim,
                quote=citation.quote,
            )
            for citation in result.citations
        ),
        duplicate=result.duplicate,
    )
