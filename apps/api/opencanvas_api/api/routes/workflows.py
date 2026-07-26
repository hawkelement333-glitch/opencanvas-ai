from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, status
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    enforce_ai_rate_limit,
    get_ai_provider,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.serialization import utc
from opencanvas_api.api.workflow_schemas import (
    WorkflowApprovalDecision,
    WorkflowDefinitionOut,
    WorkflowDraftCreate,
    WorkflowExecutionOut,
    WorkflowExecutionStart,
    WorkflowStepExecutionOut,
    WorkflowVersionCreate,
    WorkflowVersionIn,
    WorkflowVersionOut,
)
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    ControlledWorkflowDependency,
    ControlledWorkflowStep,
    ControlledWorkflowVersion,
    ControlledWorkflowVersionState,
)
from opencanvas_api.services.agents.contracts import ApprovalDecision
from opencanvas_api.services.ai import AIProvider
from opencanvas_api.services.documents.embeddings import build_embedding_provider
from opencanvas_api.services.workflows import (
    ControlledWorkflowService,
    CreateWorkflowDraft,
    CreateWorkflowVersion,
    StartWorkflow,
    WorkflowAuthorityError,
    WorkflowConflictError,
    WorkflowDefinitionRecord,
    WorkflowError,
    WorkflowExecutionRecord,
    WorkflowNotFoundError,
    WorkflowStepInput,
    WorkflowStorageError,
    WorkflowValidationError,
    WorkflowVersionInput,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/canvases/{canvas_id}/workflows")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _error(error: WorkflowError) -> ApiError:
    if isinstance(error, WorkflowNotFoundError):
        return ApiError(status.HTTP_404_NOT_FOUND, error.code, error.safe_message)
    if isinstance(error, WorkflowConflictError):
        return ApiError(status.HTTP_409_CONFLICT, error.code, error.safe_message)
    if isinstance(error, WorkflowValidationError):
        return ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.safe_message)
    if isinstance(error, WorkflowAuthorityError):
        return ApiError(status.HTTP_403_FORBIDDEN, error.code, error.safe_message)
    if isinstance(error, WorkflowStorageError):
        return ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, error.code, error.safe_message)
    return ApiError(status.HTTP_500_INTERNAL_SERVER_ERROR, error.code, error.safe_message)


def _service(
    session: AsyncSession,
    provider: AIProvider,
    settings: Settings,
) -> ControlledWorkflowService:
    return ControlledWorkflowService(
        session,
        embedding_provider=build_embedding_provider(settings),
        ai_provider=provider,
    )


def _version_input(value: WorkflowVersionIn) -> WorkflowVersionInput:
    return WorkflowVersionInput(
        steps=tuple(
            WorkflowStepInput(
                step_key=item.step_key,
                step_type=item.step_type,
                depends_on=tuple(item.depends_on),
                config=item.config,
                max_attempts=item.max_attempts,
                compensation_step_key=item.compensation_step_key,
            )
            for item in value.steps
        ),
        input_schema_version=value.input_schema_version,
        output_schema_version=value.output_schema_version,
        max_duration_seconds=value.max_duration_seconds,
        max_retries_per_step=value.max_retries_per_step,
        compensation_policy=value.compensation_policy,
    )


@router.post("", response_model=WorkflowDefinitionOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: WorkflowDraftCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowDefinitionOut:
    service = _service(session, provider, settings)
    try:
        record = await service.create_draft(
            CreateWorkflowDraft(
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                kind=payload.kind,
                name=payload.name,
                description=payload.description,
                version=_version_input(payload.version),
                idempotency_key=payload.idempotency_key,
            )
        )
        await session.commit()
    except WorkflowError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _definition_out(session, record)


@router.get("", response_model=list[WorkflowDefinitionOut])
async def list_workflows(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[WorkflowDefinitionOut]:
    try:
        records = await _service(session, provider, settings).list_definitions(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            limit=limit,
            offset=offset,
        )
    except WorkflowError as exc:
        raise _error(exc) from exc
    return [await _definition_out(session, record) for record in records]


@router.get("/{definition_id}", response_model=WorkflowDefinitionOut)
async def get_workflow(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    definition_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowDefinitionOut:
    try:
        record = await _service(session, provider, settings).get_definition(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            definition_id=definition_id,
        )
    except WorkflowError as exc:
        raise _error(exc) from exc
    return await _definition_out(session, record)


@router.post("/{definition_id}/versions", response_model=WorkflowDefinitionOut)
async def create_workflow_version(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    definition_id: uuid.UUID,
    payload: WorkflowVersionCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowDefinitionOut:
    service = _service(session, provider, settings)
    try:
        record = await service.create_version(
            CreateWorkflowVersion(
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                definition_id=definition_id,
                version=_version_input(payload.version),
                idempotency_key=payload.idempotency_key,
            )
        )
        await session.commit()
    except WorkflowError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _definition_out(session, record)


@router.post("/versions/{version_id}/validate", response_model=WorkflowVersionOut)
async def validate_workflow_version(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    version_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowVersionOut:
    return await _change_version_state(
        _service(session, provider, settings),
        session,
        operation="validate",
        user_id=principal.user_id,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
        version_id=version_id,
    )


@router.post("/versions/{version_id}/activate", response_model=WorkflowVersionOut)
async def activate_workflow_version(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    version_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowVersionOut:
    return await _change_version_state(
        _service(session, provider, settings),
        session,
        operation="activate",
        user_id=principal.user_id,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
        version_id=version_id,
    )


@router.post("/versions/{version_id}/disable", response_model=WorkflowVersionOut)
async def disable_workflow_version(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    version_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowVersionOut:
    return await _change_version_state(
        _service(session, provider, settings),
        session,
        operation="disable",
        user_id=principal.user_id,
        workspace_id=workspace_id,
        canvas_id=canvas_id,
        version_id=version_id,
    )


@router.post("/executions", response_model=WorkflowExecutionOut)
async def start_workflow(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    payload: WorkflowExecutionStart,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(enforce_ai_rate_limit)],
) -> WorkflowExecutionOut:
    service = _service(session, provider, settings)
    try:
        record = await service.start(
            StartWorkflow(
                user_id=principal.user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                version_id=payload.version_id,
                query=payload.query,
                selected_object_ids=tuple(payload.selected_object_ids),
                seed_object_ids=tuple(payload.seed_object_ids),
                idempotency_key=payload.idempotency_key,
            )
        )
        await session.commit()
    except WorkflowError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _execution_out(session, record)


@router.get("/executions/{execution_id}", response_model=WorkflowExecutionOut)
async def get_workflow_execution(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    execution_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowExecutionOut:
    try:
        record = await _service(session, provider, settings).get_execution(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )
    except WorkflowError as exc:
        raise _error(exc) from exc
    return await _execution_out(session, record)


@router.post(
    "/executions/{execution_id}/steps/{step_execution_id}/approval",
    response_model=WorkflowExecutionOut,
)
async def decide_workflow_step_approval(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    execution_id: uuid.UUID,
    step_execution_id: uuid.UUID,
    payload: WorkflowApprovalDecision,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowExecutionOut:
    session_id = principal.session_id or uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"opencanvas:test-workflow-approval-session:{principal.user_id}",
    )
    service = _service(session, provider, settings)
    try:
        record = await service.decide_approval(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            decision=ApprovalDecision(payload.decision),
            session_id=session_id,
        )
        await session.commit()
    except WorkflowError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _execution_out(session, record)


@router.post("/executions/{execution_id}/cancel", response_model=WorkflowExecutionOut)
async def cancel_workflow_execution(
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    execution_id: uuid.UUID,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    provider: ProviderDep,
    settings: SettingsDep,
) -> WorkflowExecutionOut:
    service = _service(session, provider, settings)
    try:
        record = await service.request_cancellation(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            execution_id=execution_id,
        )
        await session.commit()
    except WorkflowError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _execution_out(session, record)


async def _change_version_state(
    service: ControlledWorkflowService,
    session: AsyncSession,
    *,
    operation: Literal["validate", "activate", "disable"],
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    version_id: uuid.UUID,
) -> WorkflowVersionOut:
    try:
        if operation == "validate":
            version = await service.validate_version(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                version_id=version_id,
            )
        elif operation == "activate":
            version = await service.activate_version(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                version_id=version_id,
            )
        else:
            version = await service.disable_version(
                user_id=user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                version_id=version_id,
            )
        await session.commit()
    except WorkflowError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return await _version_out(session, version)


async def _definition_out(
    session: AsyncSession,
    record: WorkflowDefinitionRecord,
) -> WorkflowDefinitionOut:
    definition = record.definition
    return WorkflowDefinitionOut(
        definition_id=definition.definition_id,
        workspace_id=definition.workspace_id,
        canvas_id=definition.canvas_id,
        kind=definition.kind,
        name=definition.name,
        description=definition.description,
        schema_version=definition.schema_version,
        trace_id=definition.trace_id,
        created_at=utc(definition.created_at),
        versions=[await _version_out(session, item) for item in record.versions],
        duplicate=record.duplicate,
    )


async def _version_out(
    session: AsyncSession,
    version: ControlledWorkflowVersion,
) -> WorkflowVersionOut:
    state = await session.scalar(
        select(ControlledWorkflowVersionState.state)
        .where(ControlledWorkflowVersionState.version_id == version.version_id)
        .order_by(ControlledWorkflowVersionState.sequence.desc())
        .limit(1)
    )
    if state is None:
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "workflow_state_missing",
            "The controlled workflow state is unavailable.",
        )
    return WorkflowVersionOut(
        version_id=version.version_id,
        version_number=version.version_number,
        lifecycle_state=state,
        schema_version=version.schema_version,
        input_schema_version=version.input_schema_version,
        output_schema_version=version.output_schema_version,
        content_digest=version.content_digest,
        max_steps=version.max_steps,
        max_duration_seconds=version.max_duration_seconds,
        max_retries_per_step=version.max_retries_per_step,
        compensation_policy=version.compensation_policy,
        supersedes_version_id=version.supersedes_version_id,
        trace_id=version.trace_id,
        created_at=utc(version.created_at),
    )


async def _execution_out(
    session: AsyncSession,
    record: WorkflowExecutionRecord,
) -> WorkflowExecutionOut:
    execution = record.execution
    definitions = {
        item.step_id: item
        for item in (
            await session.scalars(
                select(ControlledWorkflowStep).where(
                    ControlledWorkflowStep.version_id == execution.version_id
                )
            )
        ).all()
    }
    dependencies = (
        await session.execute(
            select(
                ControlledWorkflowDependency.step_id,
                ControlledWorkflowDependency.depends_on_step_id,
            ).where(ControlledWorkflowDependency.version_id == execution.version_id)
        )
    ).all()
    dependency_keys: dict[uuid.UUID, list[str]] = {}
    for step_id, depends_on_step_id in dependencies:
        dependency = definitions.get(depends_on_step_id)
        if dependency is None:
            raise ApiError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "workflow_dependency_missing",
                "A controlled workflow dependency is unavailable.",
            )
        dependency_keys.setdefault(step_id, []).append(dependency.step_key)
    steps: list[WorkflowStepExecutionOut] = []
    for row in record.steps:
        definition = definitions.get(row.step_definition_id)
        if definition is None:
            raise ApiError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "workflow_step_missing",
                "The controlled workflow step is unavailable.",
            )
        steps.append(
            WorkflowStepExecutionOut(
                step_execution_id=row.step_execution_id,
                step_key=definition.step_key,
                step_type=definition.step_type,
                depends_on=sorted(dependency_keys.get(definition.step_id, [])),
                capability=definition.capability,
                risk_class=definition.risk_class,
                requested_action=(
                    cast(str, definition.config.get("action"))
                    if isinstance(definition.config.get("action"), str)
                    else (
                        "workflow.approval"
                        if definition.step_type == "human_approval"
                        else (
                            "reversible_effect.rollback"
                            if definition.step_type == "compensation"
                            else None
                        )
                    )
                ),
                affected_resource_id=(
                    uuid.UUID(cast(str, definition.config["noteId"]))
                    if isinstance(definition.config.get("noteId"), str)
                    else (
                        execution.canvas_id
                        if definition.step_type in {"controlled_effect", "compensation"}
                        else None
                    )
                ),
                status=row.status,
                attempt_count=row.attempt_count,
                max_attempts=row.max_attempts,
                approval_required=definition.approval_required,
                controlled_execution_id=row.controlled_execution_id,
                approval_id=row.approval_id,
                retrieval_id=row.retrieval_id,
                evidence_bundle_id=row.bundle_id,
                effect_id=row.effect_id,
                rollback_result_id=row.rollback_result_id,
                safe_failure_class=row.safe_failure_class,
                output_digest=row.output_digest,
                started_at=utc(row.started_at) if row.started_at is not None else None,
                completed_at=utc(row.completed_at) if row.completed_at is not None else None,
            )
        )
    return WorkflowExecutionOut(
        execution_id=execution.execution_id,
        definition_id=execution.definition_id,
        version_id=execution.version_id,
        workspace_id=execution.workspace_id,
        canvas_id=execution.canvas_id,
        status=execution.status,
        outcome=execution.outcome,
        plan_id=execution.plan_id,
        plan_digest=execution.plan_digest,
        input_digest=execution.input_digest,
        graph_revision=execution.graph_revision,
        selected_object_ids=[uuid.UUID(value) for value in execution.selected_object_ids],
        output=cast(dict[str, JsonValue] | None, execution.output),
        output_digest=execution.output_digest,
        trace_id=execution.trace_id,
        created_at=utc(execution.created_at),
        deadline_at=utc(execution.deadline_at),
        cancel_requested_at=(
            utc(execution.cancel_requested_at)
            if execution.cancel_requested_at is not None
            else None
        ),
        completed_at=utc(execution.completed_at) if execution.completed_at is not None else None,
        steps=steps,
        duplicate=record.duplicate,
    )


__all__ = ["router"]
