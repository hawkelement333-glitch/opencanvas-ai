from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from opencanvas_api.api.schemas import ApiModel

WorkspaceRole = Literal["owner", "administrator", "editor", "approver", "member", "viewer"]
InvitationRole = Literal["administrator", "editor", "approver", "member", "viewer"]
MembershipState = Literal["active", "suspended", "removed"]
InvitationState = Literal["pending", "accepted", "declined", "expired", "revoked"]
ResourceKind = Literal["canvas", "canonical_object", "workflow", "agent"]
ShareAccess = Literal["view", "contribute", "manage"]
ShareAudience = Literal["workspace", "membership"]
VisibilityPolicy = Literal["private", "inherit", "workspace_visible"]

COLLABORATION_PERMISSIONS = Literal[
    "workspace.view",
    "workspace.settings.manage",
    "membership.view",
    "membership.manage",
    "invitation.create",
    "invitation.resend",
    "invitation.revoke",
    "role.assign",
    "ownership.transfer.request",
    "ownership.transfer.accept",
    "ownership.transfer.cancel",
    "canvas.view",
    "canvas.edit",
    "canvas.share",
    "resource.view",
    "resource.edit",
    "resource.share",
    "comment.create",
    "comment.edit_own",
    "comment.resolve",
    "comment.moderate",
    "workflow.view",
    "workflow.edit",
    "workflow.share",
    "workflow.invoke",
    "agent.view",
    "agent.edit",
    "agent.share",
    "agent.activate_request",
    "agent.invoke",
    "approval.review",
    "collaboration_activity.view",
    "trace.view",
    "source.export",
    "evidence_bundle.view",
    "evidence_bundle.export",
]

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9._:-]+$"


class InvitationCreate(ApiModel):
    recipient_email: str = Field(min_length=3, max_length=320)
    intended_role: InvitationRole
    expires_in_days: int = Field(default=7, ge=1, le=30)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )

    @field_validator("recipient_email")
    @classmethod
    def trim_recipient_email(cls, value: str) -> str:
        return value.strip()


class InvitationCommand(ApiModel):
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )


class ShareTargetIn(ApiModel):
    resource_kind: ResourceKind
    resource_id: uuid.UUID
    audience_kind: ShareAudience
    audience_membership_id: uuid.UUID | None = None
    access_level: ShareAccess
    expires_in_days: int | None = Field(default=None, ge=1, le=30)


class ShareBatchCreate(ApiModel):
    targets: list[ShareTargetIn] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=IDEMPOTENCY_PATTERN)


class ShareRevoke(ApiModel):
    share_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=IDEMPOTENCY_PATTERN)


class ShareOut(ApiModel):
    share_id: uuid.UUID
    workspace_id: uuid.UUID
    resource_kind: ResourceKind
    resource_id: uuid.UUID
    audience_kind: ShareAudience
    audience_membership_id: uuid.UUID | None
    access_level: ShareAccess
    state: Literal["active", "revoked", "expired", "superseded"]
    authority_generation: int = Field(ge=1)
    expires_at: datetime | None
    duplicate: bool = False


class VisibilityChange(ApiModel):
    visibility_policy: VisibilityPolicy
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=IDEMPOTENCY_PATTERN)


class ResourceOwnershipOut(ApiModel):
    resource_kind: ResourceKind
    resource_id: uuid.UUID
    owner_kind: Literal["workspace", "membership"]
    owner_membership_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    visibility_policy: VisibilityPolicy
    authority_generation: int = Field(ge=1)


class OwnershipTransferCreate(ApiModel):
    transfer_kind: Literal["workspace", "resource"]
    recipient_membership_id: uuid.UUID
    resource_kind: ResourceKind | None = None
    resource_id: uuid.UUID | None = None
    expires_in_hours: int = Field(default=48, ge=1, le=168)
    former_owner_role: Literal["administrator", "editor", "approver", "member", "viewer"] = (
        "administrator"
    )
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=IDEMPOTENCY_PATTERN)


class OwnershipTransferOut(ApiModel):
    transfer_id: uuid.UUID
    workspace_id: uuid.UUID
    transfer_kind: Literal["workspace", "resource"]
    resource_kind: ResourceKind | None
    resource_id: uuid.UUID | None
    requester_membership_id: uuid.UUID
    recipient_membership_id: uuid.UUID
    state: Literal["pending", "accepted", "rejected", "canceled", "expired", "superseded"]
    authority_generation: int = Field(ge=1)
    expires_at: datetime
    duplicate: bool = False


class CommentCreate(ApiModel):
    content: str = Field(min_length=1, max_length=5_000)
    parent_comment_id: uuid.UUID | None = None
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )


class CommentRevisionCreate(ApiModel):
    expected_revision_id: uuid.UUID
    content: str = Field(min_length=1, max_length=5_000)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )


class CommentModerate(ApiModel):
    tombstone_kind: Literal["remove_by_author", "hide_by_moderation"]
    reason_code: str = Field(min_length=3, max_length=64)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )


class CommentThreadStateChange(ApiModel):
    target_state: Literal["resolved", "reopened"]
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )


class CommentOut(ApiModel):
    comment_id: uuid.UUID
    thread_id: uuid.UUID
    workspace_id: uuid.UUID
    resource_kind: ResourceKind
    resource_id: uuid.UUID
    parent_comment_id: uuid.UUID | None
    depth: int
    thread_sequence: int
    thread_state: Literal["open", "resolved", "reopened"]
    state: Literal["active", "edited", "hidden_by_moderation", "removed_by_author"]
    revision_id: uuid.UUID | None
    revision_sequence: int | None
    content: str | None
    author_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    duplicate: bool = False


class CommentRevisionOut(ApiModel):
    revision_id: uuid.UUID
    comment_id: uuid.UUID
    sequence: int
    revision_kind: Literal["created", "edited"]
    author_user_id: uuid.UUID
    content: str
    content_digest: str
    trace_id: uuid.UUID
    created_at: datetime
    duplicate: bool = False


class CommentThreadOut(ApiModel):
    thread_id: uuid.UUID
    workspace_id: uuid.UUID
    resource_kind: ResourceKind
    resource_id: uuid.UUID
    state: Literal["open", "resolved", "reopened"]
    updated_at: datetime
    duplicate: bool = False


class CollaborationActivityOut(ApiModel):
    activity_id: uuid.UUID
    event_id: uuid.UUID
    event_type: Literal[
        "comment.created",
        "comment.reply.created",
        "comment.revised",
        "comment.tombstoned",
        "comment.thread.resolved",
        "comment.thread.reopened",
        "resource.share.created",
        "resource.share.changed",
        "resource.share.revoked",
        "resource.visibility.changed",
        "resource.ownership_changed",
    ]
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID | None
    sequence: int
    resource_kind: ResourceKind
    resource_id: uuid.UUID
    comment_id: uuid.UUID | None
    thread_id: uuid.UUID | None
    actor_user_id: uuid.UUID
    trace_id: uuid.UUID
    occurred_at: datetime


class InvitationCredentialCommand(InvitationCommand):
    token: SecretStr


class MembershipRoleCommand(InvitationCommand):
    role: InvitationRole


class ApprovalAuthorityCreate(InvitationCommand):
    membership_id: uuid.UUID
    capability: Literal[
        "workspace.metadata.read",
        "canvas.snapshot.read",
        "context.selected.read",
        "document.version.read",
        "trace.scoped.read",
        "retrieval.selected.search",
        "draft.note.create",
        "draft.answer.create",
        "canvas.note.create",
        "canvas.note.update",
        "canvas.note.create.rollback",
        "canvas.note.update.rollback",
        "knowledge_graph.relationship.write",
        "workflow.step.execute",
        "evidence.bundle.create",
        "execution.cancel",
    ]
    resource_kind: Literal[
        "workspace",
        "canvas",
        "node",
        "document_version",
        "chunk",
        "trace",
        "canonical_relationship",
        "canonical_object",
    ]
    resource_id: uuid.UUID
    maximum_risk_class: Literal[
        "r0_observation",
        "r1_draft",
        "r2_transient_action",
        "r3_durable_write",
    ]
    expires_in_days: int = Field(default=7, ge=1, le=30)


class ApprovalAuthorityOut(ApiModel):
    assignment_id: uuid.UUID
    workspace_id: uuid.UUID
    membership_id: uuid.UUID
    capability: str
    resource_kind: str
    resource_id: uuid.UUID
    maximum_risk_class: str
    state: Literal["active", "revoked", "superseded"]
    valid_from: datetime
    expires_at: datetime
    duplicate: bool = False


class MembershipOut(ApiModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: WorkspaceRole
    state: MembershipState
    authority_generation: int = Field(ge=1)
    accepted_invitation_id: uuid.UUID | None
    created_at: datetime
    state_recorded_at: datetime


class WorkspaceCollaborationContextOut(ApiModel):
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_lifecycle_state: Literal["created", "active", "archived", "deleted"]
    workspace_owner_user_id: uuid.UUID
    authenticated_user_id: uuid.UUID
    membership_id: uuid.UUID
    membership_state: Literal["active"]
    role: WorkspaceRole
    authority_generation: int = Field(ge=1)
    permission_ceiling: list[COLLABORATION_PERMISSIONS]


class InvitationOut(ApiModel):
    invitation_id: uuid.UUID
    workspace_id: uuid.UUID
    recipient_email_masked: str
    intended_role: InvitationRole
    state: InvitationState
    expires_at: datetime
    created_at: datetime
    state_recorded_at: datetime
    duplicate: bool = False
    development_token: str | None = None


__all__ = [
    "ApprovalAuthorityCreate",
    "ApprovalAuthorityOut",
    "CollaborationActivityOut",
    "CommentCreate",
    "CommentModerate",
    "CommentOut",
    "CommentRevisionCreate",
    "CommentRevisionOut",
    "CommentThreadOut",
    "CommentThreadStateChange",
    "InvitationCommand",
    "InvitationCreate",
    "InvitationCredentialCommand",
    "InvitationOut",
    "InvitationRole",
    "InvitationState",
    "MembershipOut",
    "MembershipRoleCommand",
    "MembershipState",
    "OwnershipTransferCreate",
    "OwnershipTransferOut",
    "ResourceOwnershipOut",
    "ShareBatchCreate",
    "ShareOut",
    "ShareRevoke",
    "ShareTargetIn",
    "VisibilityChange",
    "WorkspaceCollaborationContextOut",
    "WorkspaceRole",
]
