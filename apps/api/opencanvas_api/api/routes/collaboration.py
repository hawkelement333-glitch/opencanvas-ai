from __future__ import annotations

import uuid
from typing import Annotated, Literal, NoReturn, cast

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.collaboration_schemas import (
    ApprovalAuthorityCreate,
    ApprovalAuthorityOut,
    CollaborationActivityOut,
    CommentCreate,
    CommentModerate,
    CommentOut,
    CommentRevisionCreate,
    CommentRevisionOut,
    CommentThreadOut,
    CommentThreadStateChange,
    InvitationCommand,
    InvitationCreate,
    InvitationCredentialCommand,
    InvitationOut,
    InvitationRole,
    MembershipOut,
    MembershipRoleCommand,
    MembershipState,
    OwnershipTransferCreate,
    OwnershipTransferOut,
    ResourceOwnershipOut,
    ShareBatchCreate,
    ShareOut,
    ShareRevoke,
    VisibilityChange,
    WorkspaceCollaborationContextOut,
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
from opencanvas_api.services.collaboration_authority import (
    ROLE_PERMISSION_CEILINGS,
    CollaborationAuthorizationService,
    CollaborationPermission,
)
from opencanvas_api.services.collaboration_comments import (
    CollaborationActivityRecord,
    CollaborationActivityService,
    CommentRecord,
    CommentService,
    CommentThreadState,
    CommentTombstoneKind,
    RevisionRecord,
    ThreadRecord,
)
from opencanvas_api.services.collaboration_management import (
    ApprovalAuthorityService,
    ApprovalAuthorityView,
    MembershipAuthorityService,
)
from opencanvas_api.services.collaboration_resources import (
    OwnershipTransferKind,
    OwnershipTransferService,
    ResourceRecord,
    ResourceVisibilityPolicy,
    ShareAccessLevel,
    ShareAudienceKind,
    ShareRecord,
    ShareResourceKind,
    ShareTarget,
    SharingService,
    TransferRecord,
)
from opencanvas_api.services.email import (
    EmailDeliveryError,
    deliver_workspace_invitation,
)

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get(
    "/workspaces/{workspace_id}/collaboration-context",
    response_model=WorkspaceCollaborationContextOut,
)
async def get_collaboration_context(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> WorkspaceCollaborationContextOut:
    decision = await CollaborationAuthorizationService(session).evaluate_permission(
        principal=principal,
        workspace_id=workspace_id,
        permission=CollaborationPermission.WORKSPACE_VIEW,
    )
    workspace = await session.get(Workspace, workspace_id)
    if (
        not decision.allowed
        or decision.membership_id is None
        or decision.role is None
        or decision.authority_generation is None
        or workspace is None
    ):
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "collaboration_not_found",
            "The requested collaboration resource was not found.",
        )
    return WorkspaceCollaborationContextOut(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        workspace_lifecycle_state=cast(
            Literal["created", "active", "archived", "deleted"],
            workspace.lifecycle_state,
        ),
        workspace_owner_user_id=workspace.owner_id,
        authenticated_user_id=principal.user_id,
        membership_id=decision.membership_id,
        membership_state="active",
        role=decision.role.value,
        authority_generation=decision.authority_generation,
        permission_ceiling=sorted(
            permission.value for permission in ROLE_PERMISSION_CEILINGS[decision.role]
        ),
    )


@router.post(
    "/workspaces/{workspace_id}/memberships/{membership_id}/role",
    response_model=MembershipOut,
)
async def change_membership_role(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MembershipRoleCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> MembershipOut:
    try:
        view = await MembershipAuthorityService(session).change_role(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=membership_id,
            role=payload.role,
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
    return _membership_out(view)


async def _membership_lifecycle(
    *,
    operation: Literal["suspend", "restore", "remove"],
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: InvitationCommand,
    principal: Principal,
    session: AsyncSession,
) -> MembershipOut:
    service = MembershipAuthorityService(session)
    try:
        method = getattr(service, operation)
        view = await method(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=membership_id,
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
    return _membership_out(view)


@router.post(
    "/workspaces/{workspace_id}/memberships/{membership_id}/suspend",
    response_model=MembershipOut,
)
async def suspend_membership(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> MembershipOut:
    return await _membership_lifecycle(
        operation="suspend",
        workspace_id=workspace_id,
        membership_id=membership_id,
        payload=payload,
        principal=principal,
        session=session,
    )


@router.post(
    "/workspaces/{workspace_id}/memberships/{membership_id}/restore",
    response_model=MembershipOut,
)
async def restore_membership(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> MembershipOut:
    return await _membership_lifecycle(
        operation="restore",
        workspace_id=workspace_id,
        membership_id=membership_id,
        payload=payload,
        principal=principal,
        session=session,
    )


@router.post(
    "/workspaces/{workspace_id}/memberships/{membership_id}/remove",
    response_model=MembershipOut,
)
async def remove_membership(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> MembershipOut:
    return await _membership_lifecycle(
        operation="remove",
        workspace_id=workspace_id,
        membership_id=membership_id,
        payload=payload,
        principal=principal,
        session=session,
    )


@router.post(
    "/workspaces/{workspace_id}/approval-authority",
    response_model=ApprovalAuthorityOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_approval_authority(
    workspace_id: uuid.UUID,
    payload: ApprovalAuthorityCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ApprovalAuthorityOut:
    try:
        view = await ApprovalAuthorityService(session).assign(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=payload.membership_id,
            capability=payload.capability,
            resource_kind=payload.resource_kind,
            resource_id=payload.resource_id,
            maximum_risk_class=payload.maximum_risk_class,
            expires_in_days=payload.expires_in_days,
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
    return _approval_authority_out(view)


@router.post(
    "/workspaces/{workspace_id}/approval-authority/{assignment_id}/replace",
    response_model=ApprovalAuthorityOut,
)
async def replace_approval_authority(
    workspace_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: ApprovalAuthorityCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ApprovalAuthorityOut:
    try:
        view = await ApprovalAuthorityService(session).assign(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=payload.membership_id,
            capability=payload.capability,
            resource_kind=payload.resource_kind,
            resource_id=payload.resource_id,
            maximum_risk_class=payload.maximum_risk_class,
            expires_in_days=payload.expires_in_days,
            idempotency_key=payload.idempotency_key,
            supersedes_assignment_id=assignment_id,
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
    return _approval_authority_out(view)


@router.post(
    "/workspaces/{workspace_id}/approval-authority/{assignment_id}/revoke",
    response_model=ApprovalAuthorityOut,
)
async def revoke_approval_authority(
    workspace_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ApprovalAuthorityOut:
    try:
        view = await ApprovalAuthorityService(session).revoke(
            principal=principal,
            workspace_id=workspace_id,
            assignment_id=assignment_id,
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
    return _approval_authority_out(view)


@router.get(
    "/workspaces/{workspace_id}/approval-authority",
    response_model=list[ApprovalAuthorityOut],
)
async def list_approval_authority(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[ApprovalAuthorityOut]:
    try:
        views = await ApprovalAuthorityService(session).list_for_workspace(
            principal=principal,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        _raise_api_error(exc)
    return [_approval_authority_out(view) for view in views]


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


@router.get(
    "/workspaces/{workspace_id}/shares",
    response_model=list[ShareOut],
)
async def list_resource_shares(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ShareOut]:
    try:
        records = await SharingService(session).list_shares(
            principal=principal,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        await _finish_error(session, exc)
    return [_share_out(record) for record in records]


@router.post(
    "/workspaces/{workspace_id}/shares",
    response_model=list[ShareOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_resource_shares(
    workspace_id: uuid.UUID,
    payload: ShareBatchCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> list[ShareOut]:
    targets = [
        ShareTarget(
            resource_kind=ShareResourceKind(item.resource_kind),
            resource_id=item.resource_id,
            audience_kind=ShareAudienceKind(item.audience_kind),
            audience_membership_id=item.audience_membership_id,
            access_level=ShareAccessLevel(item.access_level),
            expires_in_days=item.expires_in_days,
        )
        for item in payload.targets
    ]
    try:
        records = await SharingService(session).create(
            principal=principal,
            workspace_id=workspace_id,
            targets=targets,
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
    return [_share_out(record) for record in records]


@router.post(
    "/workspaces/{workspace_id}/shares/revoke",
    response_model=list[ShareOut],
)
async def revoke_resource_shares(
    workspace_id: uuid.UUID,
    payload: ShareRevoke,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> list[ShareOut]:
    try:
        records = await SharingService(session).revoke(
            principal=principal,
            workspace_id=workspace_id,
            share_ids=payload.share_ids,
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
    return [_share_out(record) for record in records]


@router.post(
    "/workspaces/{workspace_id}/resources/{resource_kind}/{resource_id}/visibility",
    response_model=ResourceOwnershipOut,
)
async def change_resource_visibility(
    workspace_id: uuid.UUID,
    resource_kind: ShareResourceKind,
    resource_id: uuid.UUID,
    payload: VisibilityChange,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> ResourceOwnershipOut:
    try:
        record = await SharingService(session).set_visibility(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            visibility_policy=ResourceVisibilityPolicy(payload.visibility_policy),
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
    return _resource_out(record)


@router.get(
    "/workspaces/{workspace_id}/resources/{resource_kind}/{resource_id}/ownership",
    response_model=ResourceOwnershipOut,
)
async def get_resource_ownership(
    workspace_id: uuid.UUID,
    resource_kind: ShareResourceKind,
    resource_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> ResourceOwnershipOut:
    decision = await SharingService(session).evaluate_access(
        principal=principal,
        workspace_id=workspace_id,
        resource_kind=resource_kind,
        resource_id=resource_id,
    )
    if not decision.allowed or decision.resource is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "collaboration_not_found",
            "The requested collaboration resource was not found.",
        )
    return _resource_out(decision.resource)


@router.post(
    "/workspaces/{workspace_id}/ownership-transfers",
    response_model=OwnershipTransferOut,
    status_code=status.HTTP_201_CREATED,
)
async def request_ownership_transfer(
    workspace_id: uuid.UUID,
    payload: OwnershipTransferCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> OwnershipTransferOut:
    try:
        record = await OwnershipTransferService(session).request(
            principal=principal,
            workspace_id=workspace_id,
            transfer_kind=OwnershipTransferKind(payload.transfer_kind),
            recipient_membership_id=payload.recipient_membership_id,
            idempotency_key=payload.idempotency_key,
            resource_kind=(
                ShareResourceKind(payload.resource_kind) if payload.resource_kind else None
            ),
            resource_id=payload.resource_id,
            expires_in_hours=payload.expires_in_hours,
            former_owner_role=payload.former_owner_role,
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
    return _transfer_out(record)


@router.get(
    "/workspaces/{workspace_id}/ownership-transfers",
    response_model=list[OwnershipTransferOut],
)
async def list_ownership_transfers(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[OwnershipTransferOut]:
    try:
        records = await OwnershipTransferService(session).list_for_workspace(
            principal=principal,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        _raise_api_error(exc)
    return [_transfer_out(record) for record in records]


async def _decide_ownership_transfer(
    *,
    decision: Literal["accept", "reject", "cancel"],
    workspace_id: uuid.UUID,
    transfer_id: uuid.UUID,
    payload: InvitationCommand,
    principal: Principal,
    session: AsyncSession,
) -> OwnershipTransferOut:
    try:
        method = getattr(OwnershipTransferService(session), decision)
        record = await method(
            principal=principal,
            workspace_id=workspace_id,
            transfer_id=transfer_id,
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
    return _transfer_out(record)


@router.post(
    "/workspaces/{workspace_id}/ownership-transfers/{transfer_id}/accept",
    response_model=OwnershipTransferOut,
)
async def accept_ownership_transfer(
    workspace_id: uuid.UUID,
    transfer_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> OwnershipTransferOut:
    return await _decide_ownership_transfer(
        decision="accept",
        workspace_id=workspace_id,
        transfer_id=transfer_id,
        payload=payload,
        principal=principal,
        session=session,
    )


@router.post(
    "/workspaces/{workspace_id}/ownership-transfers/{transfer_id}/reject",
    response_model=OwnershipTransferOut,
)
async def reject_ownership_transfer(
    workspace_id: uuid.UUID,
    transfer_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> OwnershipTransferOut:
    return await _decide_ownership_transfer(
        decision="reject",
        workspace_id=workspace_id,
        transfer_id=transfer_id,
        payload=payload,
        principal=principal,
        session=session,
    )


@router.post(
    "/workspaces/{workspace_id}/ownership-transfers/{transfer_id}/cancel",
    response_model=OwnershipTransferOut,
)
async def cancel_ownership_transfer(
    workspace_id: uuid.UUID,
    transfer_id: uuid.UUID,
    payload: InvitationCommand,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> OwnershipTransferOut:
    return await _decide_ownership_transfer(
        decision="cancel",
        workspace_id=workspace_id,
        transfer_id=transfer_id,
        payload=payload,
        principal=principal,
        session=session,
    )


@router.get(
    "/workspaces/{workspace_id}/resources/{resource_kind}/{resource_id}/comments",
    response_model=list[CommentOut],
)
async def list_comments(
    workspace_id: uuid.UUID,
    resource_kind: ShareResourceKind,
    resource_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[CommentOut]:
    try:
        records = await CommentService(session).list_comments(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        await _finish_error(session, exc)
    return [_comment_out(record) for record in records]


@router.post(
    "/workspaces/{workspace_id}/resources/{resource_kind}/{resource_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    workspace_id: uuid.UUID,
    resource_kind: ShareResourceKind,
    resource_id: uuid.UUID,
    payload: CommentCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> CommentOut:
    try:
        record = await CommentService(session).create(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            content=payload.content,
            parent_comment_id=payload.parent_comment_id,
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
    return _comment_out(record)


@router.get(
    "/workspaces/{workspace_id}/comments/{comment_id}/revisions",
    response_model=list[CommentRevisionOut],
)
async def list_comment_revisions(
    workspace_id: uuid.UUID,
    comment_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[CommentRevisionOut]:
    try:
        revisions = await CommentService(session).list_revisions(
            principal=principal,
            workspace_id=workspace_id,
            comment_id=comment_id,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        await _finish_error(session, exc)
    return [_comment_revision_out(revision) for revision in revisions]


@router.post(
    "/workspaces/{workspace_id}/comments/{comment_id}/revisions",
    response_model=CommentRevisionOut,
    status_code=status.HTTP_201_CREATED,
)
async def revise_comment(
    workspace_id: uuid.UUID,
    comment_id: uuid.UUID,
    payload: CommentRevisionCreate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> CommentRevisionOut:
    try:
        record = await CommentService(session).revise(
            principal=principal,
            workspace_id=workspace_id,
            comment_id=comment_id,
            expected_revision_id=payload.expected_revision_id,
            content=payload.content,
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
    return _revision_record_out(record)


@router.post(
    "/workspaces/{workspace_id}/comments/{comment_id}/moderate",
    response_model=CommentOut,
)
async def tombstone_comment(
    workspace_id: uuid.UUID,
    comment_id: uuid.UUID,
    payload: CommentModerate,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> CommentOut:
    try:
        record = await CommentService(session).tombstone(
            principal=principal,
            workspace_id=workspace_id,
            comment_id=comment_id,
            tombstone_kind=CommentTombstoneKind(payload.tombstone_kind),
            reason_code=payload.reason_code,
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
    return _comment_out(record)


@router.post(
    "/workspaces/{workspace_id}/comment-threads/{thread_id}/resolve",
    response_model=CommentThreadOut,
)
async def change_comment_thread_state(
    workspace_id: uuid.UUID,
    thread_id: uuid.UUID,
    payload: CommentThreadStateChange,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> CommentThreadOut:
    try:
        record = await CommentService(session).set_thread_state(
            principal=principal,
            workspace_id=workspace_id,
            thread_id=thread_id,
            target_state=CommentThreadState(payload.target_state),
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
    return _thread_out(record)


@router.get(
    "/workspaces/{workspace_id}/collaboration-activity",
    response_model=list[CollaborationActivityOut],
)
async def list_collaboration_activity(
    workspace_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    resource_kind: Annotated[ShareResourceKind | None, Query(alias="resourceKind")] = None,
    resource_id: Annotated[uuid.UUID | None, Query(alias="resourceId")] = None,
    event_type: Annotated[str | None, Query(alias="eventType", max_length=64)] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[CollaborationActivityOut]:
    try:
        records = await CollaborationActivityService(session).list_activity(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
    except CollaborationError as exc:
        await _finish_error(session, exc)
    return [_collaboration_activity_out(record) for record in records]


def _share_out(record: ShareRecord) -> ShareOut:
    share = record.share
    transition = record.transition
    return ShareOut(
        share_id=share.share_id,
        workspace_id=share.workspace_id,
        resource_kind=cast(
            Literal["canvas", "canonical_object", "workflow", "agent"], share.resource_kind
        ),
        resource_id=share.resource_id,
        audience_kind=cast(Literal["workspace", "membership"], share.audience_kind),
        audience_membership_id=share.audience_membership_id,
        access_level=cast(Literal["view", "contribute", "manage"], transition.access_level),
        state=cast(Literal["active", "revoked", "expired", "superseded"], transition.current_state),
        authority_generation=transition.authority_generation,
        expires_at=utc(transition.expires_at) if transition.expires_at else None,
        duplicate=record.duplicate,
    )


def _resource_out(record: ResourceRecord) -> ResourceOwnershipOut:
    ownership = record.ownership
    return ResourceOwnershipOut(
        resource_kind=cast(
            Literal["canvas", "canonical_object", "workflow", "agent"],
            record.resource.resource_kind,
        ),
        resource_id=record.resource.resource_id,
        owner_kind=cast(Literal["workspace", "membership"], ownership.current_owner_kind),
        owner_membership_id=ownership.current_owner_membership_id,
        owner_user_id=ownership.current_owner_user_id,
        visibility_policy=cast(
            Literal["private", "inherit", "workspace_visible"], ownership.visibility_policy
        ),
        authority_generation=ownership.authority_generation,
    )


def _transfer_out(record: TransferRecord) -> OwnershipTransferOut:
    transfer = record.transfer
    transition = record.transition
    return OwnershipTransferOut(
        transfer_id=transfer.transfer_id,
        workspace_id=transfer.workspace_id,
        transfer_kind=cast(Literal["workspace", "resource"], transfer.transfer_kind),
        resource_kind=cast(
            Literal["canvas", "canonical_object", "workflow", "agent"] | None,
            transfer.resource_kind,
        ),
        resource_id=transfer.resource_id,
        requester_membership_id=transfer.requester_membership_id,
        recipient_membership_id=transfer.recipient_membership_id,
        state=cast(
            Literal["pending", "accepted", "rejected", "canceled", "expired", "superseded"],
            transition.current_state,
        ),
        authority_generation=transition.authority_generation,
        expires_at=utc(transfer.expires_at),
        duplicate=record.duplicate,
    )


def _comment_out(record: CommentRecord) -> CommentOut:
    comment = record.comment
    revision = record.revision
    return CommentOut(
        comment_id=comment.comment_id,
        thread_id=comment.thread_id,
        workspace_id=comment.workspace_id,
        resource_kind=cast(
            Literal["canvas", "canonical_object", "workflow", "agent"],
            comment.resource_kind,
        ),
        resource_id=comment.resource_id,
        parent_comment_id=comment.parent_comment_id,
        depth=comment.depth,
        thread_sequence=comment.thread_sequence,
        thread_state=cast(
            Literal["open", "resolved", "reopened"],
            record.thread_transition.current_state,
        ),
        state=cast(
            Literal["active", "edited", "hidden_by_moderation", "removed_by_author"],
            record.transition.current_state,
        ),
        revision_id=revision.revision_id if revision else None,
        revision_sequence=revision.sequence if revision else None,
        content=revision.content if revision else None,
        author_user_id=comment.author_user_id,
        created_at=utc(comment.created_at),
        updated_at=utc(record.transition.recorded_at),
        duplicate=record.duplicate,
    )


def _comment_revision_out(revision: object) -> CommentRevisionOut:
    from opencanvas_api.db.models import CollaborationCommentRevision

    row = cast(CollaborationCommentRevision, revision)
    return CommentRevisionOut(
        revision_id=row.revision_id,
        comment_id=row.comment_id,
        sequence=row.sequence,
        revision_kind=cast(Literal["created", "edited"], row.revision_kind),
        author_user_id=row.author_user_id,
        content=row.content,
        content_digest=row.content_digest,
        trace_id=row.trace_id,
        created_at=utc(row.created_at),
    )


def _revision_record_out(record: RevisionRecord) -> CommentRevisionOut:
    return _comment_revision_out(record.revision).model_copy(update={"duplicate": record.duplicate})


def _thread_out(record: ThreadRecord) -> CommentThreadOut:
    return CommentThreadOut(
        thread_id=record.thread.thread_id,
        workspace_id=record.thread.workspace_id,
        resource_kind=cast(
            Literal["canvas", "canonical_object", "workflow", "agent"],
            record.thread.resource_kind,
        ),
        resource_id=record.thread.resource_id,
        state=cast(
            Literal["open", "resolved", "reopened"],
            record.transition.current_state,
        ),
        updated_at=utc(record.transition.recorded_at),
        duplicate=record.duplicate,
    )


def _collaboration_activity_out(
    record: CollaborationActivityRecord,
) -> CollaborationActivityOut:
    return CollaborationActivityOut(
        activity_id=record.activity_id,
        event_id=record.event_id,
        event_type=record.event_type.value,
        workspace_id=record.workspace_id,
        canvas_id=record.canvas_id,
        sequence=record.sequence,
        resource_kind=record.resource_kind.value,
        resource_id=record.resource_id,
        comment_id=record.comment_id,
        thread_id=record.thread_id,
        actor_user_id=record.actor_user_id,
        trace_id=record.trace_id,
        occurred_at=utc(record.occurred_at),
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


def _approval_authority_out(view: ApprovalAuthorityView) -> ApprovalAuthorityOut:
    assignment = view.assignment
    return ApprovalAuthorityOut(
        assignment_id=assignment.assignment_id,
        workspace_id=assignment.workspace_id,
        membership_id=assignment.membership_id,
        capability=assignment.capability,
        resource_kind=assignment.resource_kind,
        resource_id=assignment.resource_id,
        maximum_risk_class=assignment.maximum_risk_class,
        state=cast(
            Literal["active", "revoked", "superseded"],
            view.transition.current_state,
        ),
        valid_from=utc(assignment.valid_from),
        expires_at=utc(assignment.expires_at),
        duplicate=view.duplicate,
    )
