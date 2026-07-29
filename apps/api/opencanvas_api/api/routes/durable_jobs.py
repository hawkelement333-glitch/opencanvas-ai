from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.services.durable_jobs import (
    DurableJobConflictError,
    DurableJobError,
    DurableJobNotFoundError,
    DurableJobService,
    DurableJobUnavailableError,
    DurableJobValidationError,
    JobView,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/jobs")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class DurableJobStatusResponse(ApiModel):
    job_run_id: uuid.UUID
    request_id: uuid.UUID | None
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID | None
    document_id: uuid.UUID
    document_version_id: uuid.UUID | None
    status: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    deadline_at: datetime | None
    completed_at: datetime | None
    safe_error_category: str | None


class CancelDurableJobRequest(ApiModel):
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")


class DeadLetterSummary(ApiModel):
    dead_letter_id: uuid.UUID
    job_run_id: uuid.UUID
    reason_code: str
    failure_classification: str
    created_at: datetime


class ReplayDeadLetterRequest(ApiModel):
    reason_code: Literal["operator_retry", "dependency_recovered", "policy_corrected"]
    idempotency_key: str = Field(min_length=1, max_length=160)


@router.get("/dead-letters", response_model=list[DeadLetterSummary])
async def list_dead_letters(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DeadLetterSummary]:
    try:
        records = await _service(session, settings).list_dead_letters(
            principal=principal,
            workspace_id=workspace_id,
            limit=limit,
        )
    except DurableJobError as exc:
        raise _api_error(exc) from exc
    return [
        DeadLetterSummary(
            dead_letter_id=record.dead_letter_id,
            job_run_id=record.job_run_id,
            reason_code=record.reason_code,
            failure_classification=record.failure_classification,
            created_at=record.created_at,
        )
        for record in records
    ]


@router.post(
    "/dead-letters/{dead_letter_id}/replay",
    response_model=DurableJobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_dead_letter(
    workspace_id: uuid.UUID,
    dead_letter_id: uuid.UUID,
    payload: ReplayDeadLetterRequest,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> DurableJobStatusResponse:
    try:
        job = await _service(session, settings).replay(
            principal=principal,
            workspace_id=workspace_id,
            dead_letter_id=dead_letter_id,
            reason_code=payload.reason_code,
            idempotency_key=payload.idempotency_key,
        )
        view = await _service(session, settings).get_status(
            principal=principal,
            workspace_id=workspace_id,
            job_run_id=job.id,
        )
        await session.commit()
    except DurableJobError as exc:
        await session.rollback()
        raise _api_error(exc) from exc
    return _status(view)


@router.get("/{job_run_id}", response_model=DurableJobStatusResponse)
async def get_job_status(
    workspace_id: uuid.UUID,
    job_run_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> DurableJobStatusResponse:
    try:
        view = await _service(session, settings).get_status(
            principal=principal,
            workspace_id=workspace_id,
            job_run_id=job_run_id,
        )
    except DurableJobError as exc:
        raise _api_error(exc) from exc
    return _status(view)


@router.post("/{job_run_id}/cancel", response_model=DurableJobStatusResponse)
async def cancel_job(
    workspace_id: uuid.UUID,
    job_run_id: uuid.UUID,
    payload: CancelDurableJobRequest,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> DurableJobStatusResponse:
    try:
        view = await _service(session, settings).cancel(
            principal=principal,
            workspace_id=workspace_id,
            job_run_id=job_run_id,
            reason_code=payload.reason_code,
        )
        await session.commit()
    except DurableJobError as exc:
        await session.rollback()
        raise _api_error(exc) from exc
    return _status(view)


def _service(session: AsyncSession, settings: Settings) -> DurableJobService:
    return DurableJobService(
        session,
        lease_seconds=settings.processing_lease_seconds,
        max_workspace_concurrency=settings.processing_max_concurrent_per_workspace,
        max_global_concurrency=settings.processing_max_concurrent_global,
        retry_base_seconds=settings.processing_retry_base_seconds,
        retry_max_seconds=settings.processing_retry_max_seconds,
    )


def _status(view: JobView) -> DurableJobStatusResponse:
    return DurableJobStatusResponse(
        job_run_id=view.job_run_id,
        request_id=view.request_id,
        workspace_id=view.workspace_id,
        canvas_id=view.canvas_id,
        document_id=view.document_id,
        document_version_id=view.document_version_id,
        status=view.status,
        attempt_count=view.attempt_count,
        max_attempts=view.max_attempts,
        available_at=view.available_at,
        deadline_at=view.deadline_at,
        completed_at=view.completed_at,
        safe_error_category=view.safe_error_category,
    )


def _api_error(exc: DurableJobError) -> ApiError:
    if isinstance(exc, DurableJobNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, DurableJobConflictError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, DurableJobUnavailableError):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, DurableJobValidationError):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ApiError(code, exc.code, exc.safe_message)


__all__ = ["router"]
