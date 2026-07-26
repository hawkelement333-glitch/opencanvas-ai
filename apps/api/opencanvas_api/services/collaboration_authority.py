from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.services.auth import Principal


class CollaborationRole(StrEnum):
    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    EDITOR = "editor"
    APPROVER = "approver"
    MEMBER = "member"
    VIEWER = "viewer"


class CollaborationPermission(StrEnum):
    WORKSPACE_VIEW = "workspace.view"
    WORKSPACE_SETTINGS_MANAGE = "workspace.settings.manage"
    MEMBERSHIP_VIEW = "membership.view"
    MEMBERSHIP_MANAGE = "membership.manage"
    INVITATION_CREATE = "invitation.create"
    INVITATION_RESEND = "invitation.resend"
    INVITATION_REVOKE = "invitation.revoke"
    ROLE_ASSIGN = "role.assign"
    OWNERSHIP_TRANSFER_REQUEST = "ownership.transfer.request"
    OWNERSHIP_TRANSFER_ACCEPT = "ownership.transfer.accept"
    OWNERSHIP_TRANSFER_CANCEL = "ownership.transfer.cancel"
    CANVAS_VIEW = "canvas.view"
    CANVAS_EDIT = "canvas.edit"
    CANVAS_SHARE = "canvas.share"
    RESOURCE_VIEW = "resource.view"
    RESOURCE_EDIT = "resource.edit"
    RESOURCE_SHARE = "resource.share"
    COMMENT_CREATE = "comment.create"
    COMMENT_EDIT_OWN = "comment.edit_own"
    COMMENT_RESOLVE = "comment.resolve"
    COMMENT_MODERATE = "comment.moderate"
    WORKFLOW_VIEW = "workflow.view"
    WORKFLOW_EDIT = "workflow.edit"
    WORKFLOW_SHARE = "workflow.share"
    WORKFLOW_INVOKE = "workflow.invoke"
    AGENT_VIEW = "agent.view"
    AGENT_EDIT = "agent.edit"
    AGENT_SHARE = "agent.share"
    AGENT_ACTIVATE_REQUEST = "agent.activate_request"
    AGENT_INVOKE = "agent.invoke"
    APPROVAL_REVIEW = "approval.review"
    COLLABORATION_ACTIVITY_VIEW = "collaboration_activity.view"
    TRACE_VIEW = "trace.view"
    SOURCE_EXPORT = "source.export"
    EVIDENCE_BUNDLE_VIEW = "evidence_bundle.view"
    EVIDENCE_BUNDLE_EXPORT = "evidence_bundle.export"


class CollaborationAction(StrEnum):
    MEMBERSHIP_LIST = "membership.list"
    MEMBERSHIP_INSPECT = "membership.inspect"
    MEMBERSHIP_ROLE_CHANGE = "membership.role.change"
    MEMBERSHIP_SUSPEND = "membership.suspend"
    MEMBERSHIP_RESTORE = "membership.restore"
    MEMBERSHIP_REMOVE = "membership.remove"
    INVITATION_CREATE = "invitation.create"
    INVITATION_LIST = "invitation.list"
    INVITATION_RESEND = "invitation.resend"
    INVITATION_REVOKE = "invitation.revoke"
    APPROVAL_AUTHORITY_ASSIGN = "approval_authority.assign"
    APPROVAL_AUTHORITY_REPLACE = "approval_authority.replace"
    APPROVAL_AUTHORITY_REVOKE = "approval_authority.revoke"
    APPROVAL_REVIEW = "approval.review"
    SHARE_LIST = "share.list"
    SHARE_CREATE = "share.create"
    SHARE_REVOKE = "share.revoke"
    SHARE_BULK_REVOKE = "share.bulk_revoke"
    RESOURCE_VISIBILITY_CHANGE = "resource.visibility.change"
    OWNERSHIP_TRANSFER_REQUEST = "ownership_transfer.request"
    OWNERSHIP_TRANSFER_ACCEPT = "ownership_transfer.accept"
    OWNERSHIP_TRANSFER_CANCEL = "ownership_transfer.cancel"
    COMMENT_CREATE = "comment.create"
    COMMENT_REVISE = "comment.revise"
    COMMENT_TOMBSTONE = "comment.tombstone"
    COMMENT_MODERATE = "comment.moderate"
    COMMENT_THREAD_RESOLVE = "comment.thread.resolve"
    COLLABORATION_ACTIVITY_LIST = "collaboration_activity.list"


_READ = frozenset(
    {
        CollaborationPermission.WORKSPACE_VIEW,
        CollaborationPermission.CANVAS_VIEW,
        CollaborationPermission.RESOURCE_VIEW,
        CollaborationPermission.WORKFLOW_VIEW,
        CollaborationPermission.AGENT_VIEW,
        CollaborationPermission.COLLABORATION_ACTIVITY_VIEW,
        CollaborationPermission.TRACE_VIEW,
        CollaborationPermission.EVIDENCE_BUNDLE_VIEW,
    }
)
_PARTICIPATE = _READ | {
    CollaborationPermission.COMMENT_CREATE,
    CollaborationPermission.COMMENT_EDIT_OWN,
    CollaborationPermission.WORKFLOW_INVOKE,
    CollaborationPermission.AGENT_INVOKE,
}
_EDIT = _PARTICIPATE | {
    CollaborationPermission.CANVAS_EDIT,
    CollaborationPermission.RESOURCE_EDIT,
    CollaborationPermission.COMMENT_RESOLVE,
    CollaborationPermission.WORKFLOW_EDIT,
    CollaborationPermission.AGENT_EDIT,
    CollaborationPermission.SOURCE_EXPORT,
}
_ADMIN = _EDIT | {
    CollaborationPermission.MEMBERSHIP_VIEW,
    CollaborationPermission.MEMBERSHIP_MANAGE,
    CollaborationPermission.INVITATION_CREATE,
    CollaborationPermission.INVITATION_RESEND,
    CollaborationPermission.INVITATION_REVOKE,
    CollaborationPermission.ROLE_ASSIGN,
    CollaborationPermission.CANVAS_SHARE,
    CollaborationPermission.RESOURCE_SHARE,
    CollaborationPermission.COMMENT_MODERATE,
    CollaborationPermission.WORKFLOW_SHARE,
    CollaborationPermission.AGENT_SHARE,
    CollaborationPermission.AGENT_ACTIVATE_REQUEST,
    CollaborationPermission.EVIDENCE_BUNDLE_EXPORT,
    CollaborationPermission.OWNERSHIP_TRANSFER_ACCEPT,
}

ROLE_PERMISSION_CEILINGS: dict[CollaborationRole, frozenset[CollaborationPermission]] = {
    CollaborationRole.OWNER: _ADMIN
    | {
        CollaborationPermission.WORKSPACE_SETTINGS_MANAGE,
        CollaborationPermission.OWNERSHIP_TRANSFER_REQUEST,
        CollaborationPermission.OWNERSHIP_TRANSFER_CANCEL,
    },
    CollaborationRole.ADMINISTRATOR: _ADMIN,
    CollaborationRole.EDITOR: _EDIT | {CollaborationPermission.OWNERSHIP_TRANSFER_ACCEPT},
    CollaborationRole.APPROVER: _READ
    | {
        CollaborationPermission.APPROVAL_REVIEW,
        CollaborationPermission.OWNERSHIP_TRANSFER_ACCEPT,
    },
    CollaborationRole.MEMBER: _PARTICIPATE | {CollaborationPermission.OWNERSHIP_TRANSFER_ACCEPT},
    CollaborationRole.VIEWER: _READ,
}

ACTION_PERMISSIONS: dict[CollaborationAction, CollaborationPermission] = {
    CollaborationAction.MEMBERSHIP_LIST: CollaborationPermission.MEMBERSHIP_VIEW,
    CollaborationAction.MEMBERSHIP_INSPECT: CollaborationPermission.MEMBERSHIP_VIEW,
    CollaborationAction.MEMBERSHIP_ROLE_CHANGE: CollaborationPermission.ROLE_ASSIGN,
    CollaborationAction.MEMBERSHIP_SUSPEND: CollaborationPermission.MEMBERSHIP_MANAGE,
    CollaborationAction.MEMBERSHIP_RESTORE: CollaborationPermission.MEMBERSHIP_MANAGE,
    CollaborationAction.MEMBERSHIP_REMOVE: CollaborationPermission.MEMBERSHIP_MANAGE,
    CollaborationAction.INVITATION_CREATE: CollaborationPermission.INVITATION_CREATE,
    CollaborationAction.INVITATION_LIST: CollaborationPermission.MEMBERSHIP_VIEW,
    CollaborationAction.INVITATION_RESEND: CollaborationPermission.INVITATION_RESEND,
    CollaborationAction.INVITATION_REVOKE: CollaborationPermission.INVITATION_REVOKE,
    CollaborationAction.APPROVAL_AUTHORITY_ASSIGN: CollaborationPermission.ROLE_ASSIGN,
    CollaborationAction.APPROVAL_AUTHORITY_REPLACE: CollaborationPermission.ROLE_ASSIGN,
    CollaborationAction.APPROVAL_AUTHORITY_REVOKE: CollaborationPermission.ROLE_ASSIGN,
    CollaborationAction.APPROVAL_REVIEW: CollaborationPermission.APPROVAL_REVIEW,
    CollaborationAction.SHARE_LIST: CollaborationPermission.RESOURCE_SHARE,
    CollaborationAction.SHARE_CREATE: CollaborationPermission.RESOURCE_SHARE,
    CollaborationAction.SHARE_REVOKE: CollaborationPermission.RESOURCE_SHARE,
    CollaborationAction.SHARE_BULK_REVOKE: CollaborationPermission.RESOURCE_SHARE,
    CollaborationAction.RESOURCE_VISIBILITY_CHANGE: CollaborationPermission.RESOURCE_SHARE,
    CollaborationAction.OWNERSHIP_TRANSFER_REQUEST: (
        CollaborationPermission.OWNERSHIP_TRANSFER_REQUEST
    ),
    CollaborationAction.OWNERSHIP_TRANSFER_ACCEPT: (
        CollaborationPermission.OWNERSHIP_TRANSFER_ACCEPT
    ),
    CollaborationAction.OWNERSHIP_TRANSFER_CANCEL: (
        CollaborationPermission.OWNERSHIP_TRANSFER_CANCEL
    ),
    CollaborationAction.COMMENT_CREATE: CollaborationPermission.COMMENT_CREATE,
    CollaborationAction.COMMENT_REVISE: CollaborationPermission.COMMENT_EDIT_OWN,
    CollaborationAction.COMMENT_TOMBSTONE: CollaborationPermission.COMMENT_EDIT_OWN,
    CollaborationAction.COMMENT_MODERATE: CollaborationPermission.COMMENT_MODERATE,
    CollaborationAction.COMMENT_THREAD_RESOLVE: CollaborationPermission.COMMENT_RESOLVE,
    CollaborationAction.COLLABORATION_ACTIVITY_LIST: (
        CollaborationPermission.COLLABORATION_ACTIVITY_VIEW
    ),
}


@dataclass(frozen=True, slots=True)
class CollaborationAuthorityDecision:
    allowed: bool
    reason_code: str
    action: CollaborationAction | None
    permission: CollaborationPermission | None
    role: CollaborationRole | None
    membership_id: uuid.UUID | None
    workspace_id: uuid.UUID
    authority_generation: int | None


class CollaborationAuthorizationService:
    """Central deny-by-default collaboration authority resolver."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def evaluate(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        action: CollaborationAction | str,
        expected_authority_generation: int | None = None,
    ) -> CollaborationAuthorityDecision:
        try:
            closed_action = CollaborationAction(action)
        except ValueError:
            return self._deny(workspace_id, "unknown_action")
        permission = ACTION_PERMISSIONS.get(closed_action)
        if permission is None:
            return self._deny(workspace_id, "unknown_permission", action=closed_action)
        return await self.evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=permission,
            action=closed_action,
            expected_authority_generation=expected_authority_generation,
        )

    async def evaluate_permission(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        permission: CollaborationPermission | str,
        action: CollaborationAction | None = None,
        expected_authority_generation: int | None = None,
    ) -> CollaborationAuthorityDecision:
        try:
            closed_permission = CollaborationPermission(permission)
        except ValueError:
            return self._deny(workspace_id, "unknown_permission", action=action)
        workspace = await self.session.get(Workspace, workspace_id)
        if (
            workspace is None
            or workspace.lifecycle_state not in {"created", "active"}
            or workspace.deleted_at
        ):
            return self._deny(workspace_id, "workspace_inactive", action=action)
        row = await self._active_membership(principal.user_id, workspace_id)
        if row is None:
            return self._deny(workspace_id, "membership_inactive", action=action)
        membership, transition = row
        try:
            role = CollaborationRole(transition.current_role)
        except ValueError:
            return self._deny(workspace_id, "unknown_role", action=action)
        authority = await self.session.get(WorkspaceAuthorityVersion, workspace_id)
        if authority is None:
            return self._deny(workspace_id, "authority_missing", action=action)
        if (
            expected_authority_generation is not None
            and authority.authority_generation != expected_authority_generation
        ):
            return self._deny(workspace_id, "authority_stale", action=action)
        if closed_permission not in ROLE_PERMISSION_CEILINGS[role]:
            return CollaborationAuthorityDecision(
                False,
                "permission_denied",
                action,
                closed_permission,
                role,
                membership.membership_id,
                workspace_id,
                authority.authority_generation,
            )
        if action is CollaborationAction.APPROVAL_REVIEW:
            return CollaborationAuthorityDecision(
                False,
                "assignment_required",
                action,
                closed_permission,
                role,
                membership.membership_id,
                workspace_id,
                authority.authority_generation,
            )
        if (
            action
            in {
                CollaborationAction.APPROVAL_AUTHORITY_ASSIGN,
                CollaborationAction.APPROVAL_AUTHORITY_REPLACE,
                CollaborationAction.APPROVAL_AUTHORITY_REVOKE,
            }
            and role is not CollaborationRole.OWNER
        ):
            return CollaborationAuthorityDecision(
                False,
                "owner_required",
                action,
                closed_permission,
                role,
                membership.membership_id,
                workspace_id,
                authority.authority_generation,
            )
        return CollaborationAuthorityDecision(
            True,
            "allowed",
            action,
            closed_permission,
            role,
            membership.membership_id,
            workspace_id,
            authority.authority_generation,
        )

    async def _active_membership(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> tuple[WorkspaceMembership, WorkspaceMembershipTransition] | None:
        latest = (
            select(func.max(WorkspaceMembershipTransition.sequence))
            .where(WorkspaceMembershipTransition.membership_id == WorkspaceMembership.membership_id)
            .correlate(WorkspaceMembership)
            .scalar_subquery()
        )
        row = (
            await self.session.execute(
                select(WorkspaceMembership, WorkspaceMembershipTransition)
                .join(
                    WorkspaceMembershipTransition,
                    (
                        WorkspaceMembershipTransition.membership_id
                        == WorkspaceMembership.membership_id
                    )
                    & (WorkspaceMembershipTransition.sequence == latest),
                )
                .where(
                    WorkspaceMembership.user_id == user_id,
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembershipTransition.current_state == "active",
                )
            )
        ).one_or_none()
        return (row[0], row[1]) if row is not None else None

    @staticmethod
    def _deny(
        workspace_id: uuid.UUID,
        reason: str,
        *,
        action: CollaborationAction | None = None,
    ) -> CollaborationAuthorityDecision:
        return CollaborationAuthorityDecision(
            False, reason, action, None, None, None, workspace_id, None
        )


__all__ = [
    "ACTION_PERMISSIONS",
    "ROLE_PERMISSION_CEILINGS",
    "CollaborationAction",
    "CollaborationAuthorityDecision",
    "CollaborationAuthorizationService",
    "CollaborationPermission",
    "CollaborationRole",
]
