from __future__ import annotations

import uuid
from typing import Annotated, Literal, NoReturn, cast

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.collaboration_schemas import (
    InvitationCommand,
    InvitationCreate,
    InvitationCredentialCommand,
    InvitationOut,
    InvitationRole,
    MembershipOut,
    MembershipState,
    WorkspaceRole,
)
from opencanvas_api.api.dependencies import MutatingPrincipalDep, PrincipalDep, get_session
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.serialization import utc
from opencanvas_api.core.config import AppMode, Settings, get_settings
from opencanvas_api.db.models import Workspace
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration import (
    PAGE_DEFAULT,
    AcceptanceResult,
    CollaborationConflictError,
    CollaborationError,
    CollaborationLimitError,
    CollaborationNotFoundError,
    CollaborationValidationError,
    InvitationExpiredError,
    InvitationService,
    InvitationView,
    IssuedInvitation,
    MembershipService,
    MembershipView,
    mask_email,
)
from opencanvas_api.services.email import (
    EmailDeliveryError,
    deliver_workspace_invitation,
)

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get(
    "/workspaces/{workspace_id}/memberships",
    response_model=list[MembershipOut],
)
async def list_memberships(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[MembershipOut]:
    try:
        views = await MembershipService(session).list_for_workspace(
            principal=principal,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        _raise_api_error(exc)
    return [_membership_out(view) for view in views]


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    workspace_id: uuid.UUID,
    payload: InvitationCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> InvitationOut:
    service = InvitationService(session, settings=settings)
    try:
        issued = await service.create(
            principal=principal,
            workspace_id=workspace_id,
            recipient_email=payload.recipient_email,
            intended_role=payload.intended_role,
            idempotency_key=payload.idempotency_key,
            expires_in_days=payload.expires_in_days,
        )
        await _deliver(service, issued, settings=settings)
        await session.commit()
    except EmailDeliveryError as exc:
        await session.commit()
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "invitation_delivery_unavailable",
            "Invitation delivery is temporarily unavailable.",
        ) from exc
    except CollaborationError as exc:
        await _finish_error(session, exc)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "collaboration_conflict",
            "The collaboration request conflicts with current state.",
        ) from exc
    return _invitation_out(
        issued,
        include_development_token=settings.runtime_mode in {AppMode.DEVELOPMENT, AppMode.TEST},
    )


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=list[InvitationOut],
)
async def list_invitations(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[InvitationOut]:
    try:
        views = await InvitationService(session, settings=settings).list_for_workspace(
            principal=principal,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        _raise_api_error(exc)
    return [_invitation_view_out(view) for view in views]


@router.post(
    "/workspaces/{workspace_id}/invitations/{invitation_id}/resend",
    response_model=InvitationOut,
)
async def resend_invitation(
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> InvitationOut:
    service = InvitationService(session, settings=settings)
    try:
        issued = await service.resend(
            principal=principal,
            workspace_id=workspace_id,
            invitation_id=invitation_id,
            idempotency_key=payload.idempotency_key,
        )
        await _deliver(service, issued, settings=settings)
        await session.commit()
    except EmailDeliveryError as exc:
        await session.commit()
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "invitation_delivery_unavailable",
            "Invitation delivery is temporarily unavailable.",
        ) from exc
    except CollaborationError as exc:
        await _finish_error(session, exc)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "collaboration_conflict",
            "The collaboration request conflicts with current state.",
        ) from exc
    return _invitation_out(
        issued,
        include_development_token=settings.runtime_mode in {AppMode.DEVELOPMENT, AppMode.TEST},
    )


@router.post(
    "/workspaces/{workspace_id}/invitations/{invitation_id}/revoke",
    response_model=InvitationOut,
)
async def revoke_invitation(
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> InvitationOut:
    try:
        view = await InvitationService(session, settings=settings).revoke(
            principal=principal,
            workspace_id=workspace_id,
            invitation_id=invitation_id,
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except CollaborationError as exc:
        await _finish_error(session, exc)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "collaboration_conflict",
            "The collaboration request conflicts with current state.",
        ) from exc
    return _invitation_view_out(view)


@router.post(
    "/collaboration-invitations/{invitation_id}/accept",
    response_model=MembershipOut,
)
async def accept_invitation(
    invitation_id: uuid.UUID,
    payload: InvitationCredentialCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> MembershipOut:
    result = await _accept_with_concurrency_retry(
        session=session,
        settings=settings,
        principal=principal,
        invitation_id=invitation_id,
        payload=payload,
    )
    return _membership_out(result.membership)


@router.post(
    "/collaboration-invitations/{invitation_id}/decline",
    response_model=InvitationOut,
)
async def decline_invitation(
    invitation_id: uuid.UUID,
    payload: InvitationCredentialCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> InvitationOut:
    try:
        view = await InvitationService(session, settings=settings).decline(
            principal=principal,
            invitation_id=invitation_id,
            raw_token=payload.token.get_secret_value(),
            idempotency_key=payload.idempotency_key,
        )
        await session.commit()
    except CollaborationError as exc:
        await _finish_error(session, exc)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "collaboration_conflict",
            "The collaboration request conflicts with current state.",
        ) from exc
    return _invitation_view_out(view)


async def _accept_with_concurrency_retry(
    *,
    session: AsyncSession,
    settings: Settings,
    principal: Principal,
    invitation_id: uuid.UUID,
    payload: InvitationCredentialCommand,
) -> AcceptanceResult:
    for attempt in range(2):
        try:
            result = await InvitationService(session, settings=settings).accept(
                principal=principal,
                invitation_id=invitation_id,
                raw_token=payload.token.get_secret_value(),
                idempotency_key=payload.idempotency_key,
            )
            await session.commit()
            return result
        except InvitationExpiredError as exc:
            await _finish_error(session, exc)
        except CollaborationError as exc:
            await session.rollback()
            _raise_api_error(exc)
        except IntegrityError as exc:
            await session.rollback()
            if attempt == 0:
                continue
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "collaboration_conflict",
                "The collaboration request conflicts with current state.",
            ) from exc
    raise RuntimeError("unreachable")


async def _deliver(
    service: InvitationService,
    issued: IssuedInvitation,
    *,
    settings: Settings,
) -> None:
    if issued.raw_token is None or issued.secret_sequence is None:
        return
    invitation = issued.view.invitation
    workspace = await service.session.get(Workspace, invitation.workspace_id)
    if workspace is None:
        raise CollaborationNotFoundError()
    channel = "smtp" if settings.password_reset_provider == "smtp" else "development_token"
    try:
        if channel == "smtp":
            await deliver_workspace_invitation(
                settings=settings,
                recipient=invitation.recipient_email_normalized,
                workspace_name=workspace.name,
                raw_token=issued.raw_token,
            )
    except EmailDeliveryError:
        await service.record_delivery(
            invitation_id=invitation.invitation_id,
            workspace_id=invitation.workspace_id,
            secret_sequence=issued.secret_sequence,
            channel="smtp",
            outcome="failed",
            failure_code="provider_failure",
            trace_id=issued.trace_id,
        )
        raise
    await service.record_delivery(
        invitation_id=invitation.invitation_id,
        workspace_id=invitation.workspace_id,
        secret_sequence=issued.secret_sequence,
        channel=cast(Literal["development_token", "smtp"], channel),
        outcome="delivered",
        trace_id=issued.trace_id,
    )


async def _finish_error(session: AsyncSession, exc: CollaborationError) -> NoReturn:
    if isinstance(exc, InvitationExpiredError) and exc.transition_persisted:
        await session.commit()
    else:
        await session.rollback()
    _raise_api_error(exc)


def _raise_api_error(exc: CollaborationError) -> NoReturn:
    if isinstance(exc, CollaborationNotFoundError):
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "collaboration_not_found",
            "The requested collaboration resource was not found.",
        ) from exc
    if isinstance(exc, InvitationExpiredError):
        raise ApiError(
            status.HTTP_410_GONE,
            exc.code,
            exc.safe_message,
        ) from exc
    if isinstance(exc, CollaborationLimitError):
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            exc.code,
            exc.safe_message,
        ) from exc
    if isinstance(exc, CollaborationValidationError):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            exc.code,
            exc.safe_message,
        ) from exc
    if isinstance(exc, CollaborationConflictError):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            exc.code,
            exc.safe_message,
        ) from exc
    raise ApiError(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "collaboration_error",
        "The collaboration operation could not be completed.",
    ) from exc


def _membership_out(view: MembershipView) -> MembershipOut:
    return MembershipOut(
        membership_id=view.membership.membership_id,
        user_id=view.membership.user_id,
        workspace_id=view.membership.workspace_id,
        role=cast(WorkspaceRole, view.transition.current_role),
        state=cast(MembershipState, view.transition.current_state),
        authority_generation=view.transition.authority_generation,
        accepted_invitation_id=view.membership.accepted_invitation_id,
        created_at=utc(view.membership.created_at),
        state_recorded_at=utc(view.transition.recorded_at),
    )


def _invitation_view_out(view: InvitationView) -> InvitationOut:
    return InvitationOut(
        invitation_id=view.invitation.invitation_id,
        workspace_id=view.invitation.workspace_id,
        recipient_email_masked=mask_email(view.invitation.recipient_email_normalized),
        intended_role=cast(InvitationRole, view.invitation.intended_role),
        state=view.effective_state,
        expires_at=utc(view.invitation.expires_at),
        created_at=utc(view.invitation.created_at),
        state_recorded_at=utc(view.transition.recorded_at),
    )


def _invitation_out(
    issued: IssuedInvitation,
    *,
    include_development_token: bool,
) -> InvitationOut:
    output = _invitation_view_out(issued.view)
    return output.model_copy(
        update={
            "duplicate": issued.duplicate,
            "development_token": issued.raw_token if include_development_token else None,
        }
    )
