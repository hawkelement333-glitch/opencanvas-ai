from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import JsonValue
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    CollaborationAuditEvent,
    CollaborationRequestIdentity,
    User,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceInvitation,
    WorkspaceInvitationDeliveryAttempt,
    WorkspaceInvitationSecretVersion,
    WorkspaceInvitationTransition,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.services.auth import AuthenticationError, Principal, normalize_email
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import CompleteTraceInput, StartTraceInput, TraceService

COLLABORATION_POLICY_VERSION = "collaboration-policy-v1"
MEMBERSHIP_LIMIT_PER_WORKSPACE = 500
WORKSPACE_LIMIT_PER_USER = 100
PENDING_INVITATION_LIMIT_PER_WORKSPACE = 100
INVITATION_DEFAULT_DAYS = 7
INVITATION_MAX_DAYS = 30
INVITATION_RESEND_MINUTES = 10
INVITATION_RESENDS_PER_DAY = 5
PAGE_DEFAULT = 50
PAGE_MAX = 100

WorkspaceRole = Literal["owner", "administrator", "editor", "approver", "member", "viewer"]
InvitationRole = Literal["administrator", "editor", "approver", "member", "viewer"]
MembershipState = Literal["active", "suspended", "removed"]
InvitationState = Literal["pending", "accepted", "declined", "expired", "revoked"]
DeliveryChannel = Literal["development_token", "smtp"]
DeliveryOutcome = Literal["delivered", "failed"]

INVITATION_ROLES = frozenset({"administrator", "editor", "approver", "member", "viewer"})


class CollaborationError(RuntimeError):
    code = "collaboration_error"
    safe_message = "The collaboration operation could not be completed."


class CollaborationNotFoundError(CollaborationError):
    code = "collaboration_not_found"
    safe_message = "The requested collaboration resource was not found."


class CollaborationConflictError(CollaborationError):
    code = "collaboration_conflict"
    safe_message = "The collaboration request conflicts with current state."


class CollaborationLimitError(CollaborationError):
    code = "collaboration_limit_reached"
    safe_message = "The collaboration limit has been reached."


class CollaborationValidationError(CollaborationError):
    code = "collaboration_invalid"
    safe_message = "The collaboration request is invalid."


class InvitationExpiredError(CollaborationConflictError):
    code = "invitation_expired"
    safe_message = "The invitation is invalid or has expired."

    def __init__(self, *, transition_persisted: bool = False) -> None:
        super().__init__(self.safe_message)
        self.transition_persisted = transition_persisted


@dataclass(frozen=True, slots=True)
class MembershipView:
    membership: WorkspaceMembership
    transition: WorkspaceMembershipTransition


@dataclass(frozen=True, slots=True)
class InvitationView:
    invitation: WorkspaceInvitation
    transition: WorkspaceInvitationTransition
    effective_state: InvitationState


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    view: InvitationView
    raw_token: str | None
    secret_sequence: int | None
    trace_id: uuid.UUID
    duplicate: bool


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    membership: MembershipView
    duplicate: bool


class MembershipService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def bootstrap_owner_membership(
        self,
        *,
        workspace: Workspace,
        actor_user_id: uuid.UUID,
        trace_id: uuid.UUID | None = None,
    ) -> MembershipView:
        if workspace.owner_id != actor_user_id:
            raise CollaborationNotFoundError()
        existing = await self.resolve(
            user_id=actor_user_id,
            workspace_id=workspace.id,
            require_active=False,
        )
        if existing is not None:
            if existing.transition.current_role != "owner":
                raise CollaborationConflictError("Workspace owner membership is inconsistent.")
            return existing

        now = self._now()
        operation_trace_id = trace_id or uuid.uuid5(workspace.id, "owner-membership-trace")
        if trace_id is None:
            await self.trace.start_trace(
                StartTraceInput(
                    trace_id=operation_trace_id,
                    event_type="collaboration.membership",
                    actor_id=str(actor_user_id),
                    actor_type="user",
                    user_id=actor_user_id,
                    workspace_id=workspace.id,
                    object_id=workspace.id,
                    object_type="workspace",
                    operation="bootstrap_owner_membership",
                    metadata={"policyVersion": COLLABORATION_POLICY_VERSION},
                )
            )
        audit = self._audit(
            workspace_id=workspace.id,
            actor_user_id=actor_user_id,
            subject_kind="workspace_membership",
            subject_id=uuid.uuid5(workspace.id, "owner-membership"),
            action="membership.bootstrap_owner",
            reason_code="workspace_owner_bootstrap",
            trace_id=operation_trace_id,
            metadata={"role": "owner", "state": "active"},
            recorded_at=now,
        )
        authority = await self._ensure_authority(workspace.id, operation_trace_id, now)
        membership = WorkspaceMembership(
            membership_id=audit.subject_id,
            user_id=actor_user_id,
            workspace_id=workspace.id,
            created_by_user_id=actor_user_id,
            accepted_invitation_id=None,
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            creation_trace_id=operation_trace_id,
            creation_audit_event_id=audit.audit_event_id,
            created_at=now,
        )
        transition = WorkspaceMembershipTransition(
            transition_id=uuid.uuid5(membership.membership_id, "transition:0"),
            membership_id=membership.membership_id,
            user_id=membership.user_id,
            workspace_id=membership.workspace_id,
            sequence=0,
            previous_state=None,
            current_state="active",
            previous_role=None,
            current_role="owner",
            reason_code="workspace_owner_bootstrap",
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            authority_generation=authority.authority_generation,
            actor_user_id=actor_user_id,
            trace_id=operation_trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add_all((audit, membership, transition))
        await self.session.flush()
        await self.events.record(
            CreateDomainEvent(
                event_type="membership.activated",
                user_id=workspace.owner_id,
                workspace_id=workspace.id,
                canvas_id=None,
                subject_id=membership.membership_id,
                actor_user_id=actor_user_id,
                source_identity=f"membership:{membership.membership_id}:activated",
                trace_id=operation_trace_id,
                audit_event_id=audit.audit_event_id,
                payload={
                    "state": "active",
                    "role": "owner",
                    "reasonCode": "workspace_owner_bootstrap",
                    "authorityGeneration": authority.authority_generation,
                },
                origin_type="authenticated_user",
            )
        )
        if trace_id is None:
            await self.trace.complete_trace(
                CompleteTraceInput(
                    trace_id=operation_trace_id,
                    event_type="collaboration.membership",
                    actor_id=str(actor_user_id),
                    actor_type="user",
                    user_id=actor_user_id,
                    workspace_id=workspace.id,
                    object_id=membership.membership_id,
                    object_type="workspace_membership",
                    operation="bootstrap_owner_membership",
                    metadata={"state": "active", "role": "owner"},
                )
            )
        return MembershipView(membership, transition)

    async def require_owner(
        self, *, principal: Principal, workspace_id: uuid.UUID
    ) -> tuple[Workspace, MembershipView]:
        workspace = await self.session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.owner_id == principal.user_id,
                Workspace.deleted_at.is_(None),
                Workspace.lifecycle_state != "deleted",
            )
        )
        if workspace is None:
            raise CollaborationNotFoundError()
        membership = await self.resolve(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            require_active=True,
        )
        if membership is None or membership.transition.current_role != "owner":
            raise CollaborationNotFoundError()
        return workspace, membership

    async def resolve(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        require_active: bool = True,
    ) -> MembershipView | None:
        latest = (
            select(func.max(WorkspaceMembershipTransition.sequence))
            .where(WorkspaceMembershipTransition.membership_id == WorkspaceMembership.membership_id)
            .correlate(WorkspaceMembership)
            .scalar_subquery()
        )
        statement = (
            select(WorkspaceMembership, WorkspaceMembershipTransition)
            .join(
                WorkspaceMembershipTransition,
                (WorkspaceMembershipTransition.membership_id == WorkspaceMembership.membership_id)
                & (WorkspaceMembershipTransition.sequence == latest),
            )
            .where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.workspace_id == workspace_id,
            )
            .order_by(WorkspaceMembership.created_at.desc(), WorkspaceMembership.membership_id)
        )
        rows = (await self.session.execute(statement)).all()
        for membership, transition in rows:
            if transition.current_state != "removed":
                if require_active and transition.current_state != "active":
                    return None
                return MembershipView(membership, transition)
        return None

    async def get(
        self,
        *,
        membership_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> MembershipView | None:
        latest = (
            select(func.max(WorkspaceMembershipTransition.sequence))
            .where(WorkspaceMembershipTransition.membership_id == membership_id)
            .scalar_subquery()
        )
        row = (
            await self.session.execute(
                select(WorkspaceMembership, WorkspaceMembershipTransition)
                .join(
                    WorkspaceMembershipTransition,
                    WorkspaceMembershipTransition.membership_id
                    == WorkspaceMembership.membership_id,
                )
                .where(
                    WorkspaceMembership.membership_id == membership_id,
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembershipTransition.sequence == latest,
                )
            )
        ).one_or_none()
        return MembershipView(row[0], row[1]) if row is not None else None

    async def list_for_workspace(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        limit: int = PAGE_DEFAULT,
        offset: int = 0,
    ) -> list[MembershipView]:
        await self.require_owner(principal=principal, workspace_id=workspace_id)
        _pagination(limit, offset)
        latest = (
            select(func.max(WorkspaceMembershipTransition.sequence))
            .where(WorkspaceMembershipTransition.membership_id == WorkspaceMembership.membership_id)
            .correlate(WorkspaceMembership)
            .scalar_subquery()
        )
        rows = (
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
                .where(WorkspaceMembership.workspace_id == workspace_id)
                .order_by(WorkspaceMembership.created_at, WorkspaceMembership.membership_id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [MembershipView(row[0], row[1]) for row in rows]

    async def active_workspace_ids(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[uuid.UUID]:
        _pagination(limit, offset)
        latest = (
            select(func.max(WorkspaceMembershipTransition.sequence))
            .where(WorkspaceMembershipTransition.membership_id == WorkspaceMembership.membership_id)
            .correlate(WorkspaceMembership)
            .scalar_subquery()
        )
        return list(
            (
                await self.session.scalars(
                    select(WorkspaceMembership.workspace_id)
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
                        WorkspaceMembershipTransition.current_state == "active",
                    )
                    .order_by(WorkspaceMembership.created_at, WorkspaceMembership.membership_id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )

    async def _ensure_authority(
        self, workspace_id: uuid.UUID, trace_id: uuid.UUID, now: datetime
    ) -> WorkspaceAuthorityVersion:
        authority = await self.session.get(WorkspaceAuthorityVersion, workspace_id)
        if authority is None:
            authority = WorkspaceAuthorityVersion(
                workspace_id=workspace_id,
                authority_generation=1,
                last_trace_id=trace_id,
                updated_at=now,
            )
            self.session.add(authority)
            await self.session.flush()
        return authority

    def _audit(
        self,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        subject_kind: str,
        subject_id: uuid.UUID,
        action: str,
        reason_code: str,
        trace_id: uuid.UUID,
        metadata: dict[str, object],
        recorded_at: datetime,
    ) -> CollaborationAuditEvent:
        return CollaborationAuditEvent(
            audit_event_id=uuid.uuid4(),
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            action=action,
            outcome="succeeded",
            reason_code=reason_code,
            metadata_digest=_digest(metadata),
            trace_id=trace_id,
            recorded_at=recorded_at,
        )

    def _now(self) -> datetime:
        return _aware_utc(self._now_factory())


class InvitationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.memberships = MembershipService(session, now_factory=self._now_factory)
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def create(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        recipient_email: str,
        intended_role: str,
        idempotency_key: str,
        expires_in_days: int = INVITATION_DEFAULT_DAYS,
    ) -> IssuedInvitation:
        workspace, inviter_membership = await self.memberships.require_owner(
            principal=principal,
            workspace_id=workspace_id,
        )
        role = _invitation_role(intended_role)
        _idempotency_key(idempotency_key)
        if not 1 <= expires_in_days <= INVITATION_MAX_DAYS:
            raise CollaborationValidationError("Invitation expiration is outside its bounds.")
        try:
            normalized_email = normalize_email(recipient_email)
        except AuthenticationError as exc:
            raise CollaborationValidationError("Invitation recipient is invalid.") from exc
        recipient_digest = self._recipient_digest(normalized_email)
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "recipientDigest": recipient_digest,
                "role": role,
                "expiresInDays": expires_in_days,
            }
        )
        replay = await self._request_replay(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="invitation.create",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            view = await self.get(replay.result_id, workspace_id=workspace_id)
            if view is None:
                raise CollaborationConflictError("Invitation replay evidence is incomplete.")
            return IssuedInvitation(
                view=view,
                raw_token=None,
                secret_sequence=None,
                trace_id=view.invitation.creation_trace_id,
                duplicate=True,
            )

        if await self._pending_count(workspace_id) >= PENDING_INVITATION_LIMIT_PER_WORKSPACE:
            raise CollaborationLimitError("The pending invitation limit has been reached.")
        existing = await self._pending_for_recipient(workspace_id, recipient_digest)
        if existing is not None:
            raise CollaborationConflictError(
                "A pending invitation already exists for this recipient."
            )

        now = self._now()
        invitation_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=invitation_id,
                object_type="workspace_invitation",
                operation="create_invitation",
                metadata={"role": role, "expiresInDays": expires_in_days},
            )
        )
        audit = self.memberships._audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="workspace_invitation",
            subject_id=invitation_id,
            action="invitation.create",
            reason_code="invitation_created",
            trace_id=trace_id,
            metadata={"role": role, "recipientDigest": recipient_digest},
            recorded_at=now,
        )
        recipient_user_id = await self.session.scalar(
            select(User.id).where(User.email_normalized == normalized_email)
        )
        invitation = WorkspaceInvitation(
            invitation_id=invitation_id,
            workspace_id=workspace_id,
            recipient_email_normalized=normalized_email,
            recipient_digest=recipient_digest,
            recipient_user_id=recipient_user_id,
            intended_role=role,
            inviter_user_id=principal.user_id,
            inviter_membership_id=inviter_membership.membership.membership_id,
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            request_digest=request_digest,
            expires_at=now + timedelta(days=expires_in_days),
            creation_trace_id=trace_id,
            creation_audit_event_id=audit.audit_event_id,
            created_at=now,
        )
        transition = WorkspaceInvitationTransition(
            transition_id=uuid.uuid5(invitation_id, "transition:0"),
            invitation_id=invitation_id,
            workspace_id=workspace_id,
            sequence=0,
            previous_state=None,
            current_state="pending",
            reason_code="invitation_created",
            result_membership_id=None,
            actor_user_id=principal.user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        raw_token = secrets.token_urlsafe(32)
        secret = WorkspaceInvitationSecretVersion(
            secret_version_id=uuid.uuid5(invitation_id, "secret:0"),
            invitation_id=invitation_id,
            workspace_id=workspace_id,
            sequence=0,
            token_hash=self._token_hash(raw_token),
            trace_id=trace_id,
            created_at=now,
        )
        request = self._request_identity(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="invitation.create",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_kind="workspace_invitation",
            result_id=invitation_id,
            trace_id=trace_id,
            now=now,
        )
        self.session.add_all((audit, invitation, transition, secret, request))
        await self.session.flush()
        await self._record_event(
            workspace=workspace,
            event_type="invitation.created",
            invitation=invitation,
            actor_user_id=principal.user_id,
            state="pending",
            reason_code="invitation_created",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=invitation_id,
                object_type="workspace_invitation",
                operation="create_invitation",
                metadata={"state": "pending", "role": role},
            )
        )
        return IssuedInvitation(
            view=InvitationView(invitation, transition, "pending"),
            raw_token=raw_token,
            secret_sequence=0,
            trace_id=trace_id,
            duplicate=False,
        )

    async def resend(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        invitation_id: uuid.UUID,
        idempotency_key: str,
    ) -> IssuedInvitation:
        await self.memberships.require_owner(principal=principal, workspace_id=workspace_id)
        _idempotency_key(idempotency_key)
        request_digest = _digest(
            {"workspaceId": str(workspace_id), "invitationId": str(invitation_id)}
        )
        replay = await self._request_replay(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="invitation.resend",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            view = await self.get(invitation_id, workspace_id=workspace_id)
            if view is None:
                raise CollaborationNotFoundError()
            return IssuedInvitation(
                view=view,
                raw_token=None,
                secret_sequence=None,
                trace_id=view.invitation.creation_trace_id,
                duplicate=True,
            )
        view = await self._require_pending(invitation_id, workspace_id)
        now = self._now()
        await self._expire_or_continue(view, principal.user_id, now)
        attempts = list(
            (
                await self.session.scalars(
                    select(WorkspaceInvitationDeliveryAttempt)
                    .where(
                        WorkspaceInvitationDeliveryAttempt.invitation_id == invitation_id,
                        WorkspaceInvitationDeliveryAttempt.recorded_at >= now - timedelta(hours=24),
                    )
                    .order_by(WorkspaceInvitationDeliveryAttempt.sequence.desc())
                )
            ).all()
        )
        if attempts and _aware_utc(attempts[0].recorded_at) > now - timedelta(
            minutes=INVITATION_RESEND_MINUTES
        ):
            raise CollaborationLimitError("Invitation resend is temporarily limited.")
        if len(attempts) >= INVITATION_RESENDS_PER_DAY + 1:
            raise CollaborationLimitError("Invitation resend is temporarily limited.")
        latest_secret = await self._latest_secret(invitation_id)
        if latest_secret is None:
            raise CollaborationConflictError("Invitation secret evidence is incomplete.")
        sequence = latest_secret.sequence + 1
        raw_token = secrets.token_urlsafe(32)
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=invitation_id,
                object_type="workspace_invitation",
                operation="resend_invitation",
                metadata={"secretSequence": sequence},
            )
        )
        audit = self.memberships._audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="workspace_invitation",
            subject_id=invitation_id,
            action="invitation.resend",
            reason_code="invitation_secret_rotated",
            trace_id=trace_id,
            metadata={"secretSequence": sequence},
            recorded_at=now,
        )
        self.session.add_all(
            (
                audit,
                WorkspaceInvitationSecretVersion(
                    secret_version_id=uuid.uuid5(invitation_id, f"secret:{sequence}"),
                    invitation_id=invitation_id,
                    workspace_id=workspace_id,
                    sequence=sequence,
                    token_hash=self._token_hash(raw_token),
                    trace_id=trace_id,
                    created_at=now,
                ),
                self._request_identity(
                    actor_user_id=principal.user_id,
                    workspace_id=workspace_id,
                    operation="invitation.resend",
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    result_kind="workspace_invitation",
                    result_id=invitation_id,
                    trace_id=trace_id,
                    now=now,
                ),
            )
        )
        await self.session.flush()
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=invitation_id,
                object_type="workspace_invitation",
                operation="resend_invitation",
                metadata={"secretSequence": sequence, "state": "pending"},
            )
        )
        return IssuedInvitation(
            view=view,
            raw_token=raw_token,
            secret_sequence=sequence,
            trace_id=trace_id,
            duplicate=False,
        )

    async def accept(
        self,
        *,
        principal: Principal,
        invitation_id: uuid.UUID,
        raw_token: str,
        idempotency_key: str,
    ) -> AcceptanceResult:
        _idempotency_key(idempotency_key)
        invitation, current, token_secret = await self._credential_view(invitation_id, raw_token)
        workspace = await self.session.get(Workspace, invitation.workspace_id)
        if workspace is None or workspace.deleted_at is not None:
            raise CollaborationNotFoundError()
        self._require_recipient(principal, invitation)
        request_digest = _digest(
            {
                "invitationId": str(invitation_id),
                "tokenHash": token_secret.token_hash,
                "actorUserId": str(principal.user_id),
            }
        )
        replay = await self._request_replay(
            actor_user_id=principal.user_id,
            workspace_id=invitation.workspace_id,
            operation="invitation.accept",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            membership = await self.memberships.get(
                membership_id=replay.result_id,
                workspace_id=invitation.workspace_id,
            )
            if membership is None:
                raise CollaborationConflictError("Invitation replay evidence is incomplete.")
            return AcceptanceResult(membership, duplicate=True)
        if current.current_state == "accepted":
            if current.result_membership_id is None:
                raise CollaborationConflictError("Invitation acceptance evidence is incomplete.")
            membership = await self.memberships.get(
                membership_id=current.result_membership_id,
                workspace_id=invitation.workspace_id,
            )
            if membership is None or membership.membership.user_id != principal.user_id:
                raise CollaborationNotFoundError()
            return AcceptanceResult(membership, duplicate=True)
        if current.current_state != "pending":
            raise CollaborationNotFoundError()
        now = self._now()
        if _aware_utc(invitation.expires_at) <= now:
            await self._append_invitation_transition(
                workspace=workspace,
                invitation=invitation,
                previous=current,
                target_state="expired",
                actor_user_id=principal.user_id,
                reason_code="invitation_expired",
                result_membership_id=None,
            )
            raise InvitationExpiredError(transition_persisted=True)

        existing = await self.memberships.resolve(
            user_id=principal.user_id,
            workspace_id=invitation.workspace_id,
            require_active=False,
        )
        created = existing is None
        if existing is not None and existing.transition.current_state != "active":
            raise CollaborationConflictError("Existing membership is not active.")
        if created:
            if await self._active_membership_count(invitation.workspace_id) >= (
                MEMBERSHIP_LIMIT_PER_WORKSPACE
            ):
                raise CollaborationLimitError("The workspace membership limit has been reached.")
            if await self._active_workspace_count(principal.user_id) >= WORKSPACE_LIMIT_PER_USER:
                raise CollaborationLimitError("The user workspace limit has been reached.")

        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=invitation.workspace_id,
                object_id=invitation.invitation_id,
                object_type="workspace_invitation",
                operation="accept_invitation",
                metadata={"role": invitation.intended_role},
            )
        )
        audit = self.memberships._audit(
            workspace_id=invitation.workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="workspace_invitation",
            subject_id=invitation.invitation_id,
            action="invitation.accept",
            reason_code="invitation_accepted",
            trace_id=trace_id,
            metadata={"role": invitation.intended_role},
            recorded_at=now,
        )
        self.session.add(audit)
        authority_generation = (
            await self._increment_authority(invitation.workspace_id, trace_id, now)
            if created
            else (
                await self._authority(invitation.workspace_id, trace_id, now)
            ).authority_generation
        )
        if existing is None:
            membership_id = uuid.uuid4()
            membership_audit = self.memberships._audit(
                workspace_id=invitation.workspace_id,
                actor_user_id=principal.user_id,
                subject_kind="workspace_membership",
                subject_id=membership_id,
                action="membership.activate",
                reason_code="invitation_accepted",
                trace_id=trace_id,
                metadata={"role": invitation.intended_role},
                recorded_at=now,
            )
            membership_identity = WorkspaceMembership(
                membership_id=membership_id,
                user_id=principal.user_id,
                workspace_id=invitation.workspace_id,
                created_by_user_id=principal.user_id,
                accepted_invitation_id=invitation.invitation_id,
                collaboration_policy_version=COLLABORATION_POLICY_VERSION,
                creation_trace_id=trace_id,
                creation_audit_event_id=membership_audit.audit_event_id,
                created_at=now,
            )
            membership_transition = WorkspaceMembershipTransition(
                transition_id=uuid.uuid5(membership_id, "transition:0"),
                membership_id=membership_id,
                user_id=principal.user_id,
                workspace_id=invitation.workspace_id,
                sequence=0,
                previous_state=None,
                current_state="active",
                previous_role=None,
                current_role=invitation.intended_role,
                reason_code="invitation_accepted",
                collaboration_policy_version=COLLABORATION_POLICY_VERSION,
                authority_generation=authority_generation,
                actor_user_id=principal.user_id,
                trace_id=trace_id,
                audit_event_id=membership_audit.audit_event_id,
                recorded_at=now,
            )
            self.session.add_all((membership_audit, membership_identity, membership_transition))
            # Materialize the accepted membership before the invitation transition
            # references it. The whole operation remains in the caller's transaction,
            # while SQLite and PostgreSQL both observe the same dependency order.
            await self.session.flush((membership_audit, membership_identity, membership_transition))
            membership = MembershipView(membership_identity, membership_transition)
        else:
            membership = existing
        accepted = WorkspaceInvitationTransition(
            transition_id=uuid.uuid5(invitation.invitation_id, "transition:accepted"),
            invitation_id=invitation.invitation_id,
            workspace_id=invitation.workspace_id,
            sequence=current.sequence + 1,
            previous_state=current.current_state,
            current_state="accepted",
            reason_code="invitation_accepted",
            result_membership_id=membership.membership.membership_id,
            actor_user_id=principal.user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        request = self._request_identity(
            actor_user_id=principal.user_id,
            workspace_id=invitation.workspace_id,
            operation="invitation.accept",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_kind="workspace_membership",
            result_id=membership.membership.membership_id,
            trace_id=trace_id,
            now=now,
        )
        self.session.add_all((accepted, request))
        await self.session.flush()
        await self._record_event(
            workspace=workspace,
            event_type="invitation.accepted",
            invitation=invitation,
            actor_user_id=principal.user_id,
            state="accepted",
            reason_code="invitation_accepted",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            membership_id=membership.membership.membership_id,
            authority_generation=authority_generation,
        )
        if created:
            await self.events.record(
                CreateDomainEvent(
                    event_type="membership.activated",
                    user_id=workspace.owner_id,
                    workspace_id=workspace.id,
                    canvas_id=None,
                    subject_id=membership.membership.membership_id,
                    actor_user_id=principal.user_id,
                    source_identity=f"membership:{membership.membership.membership_id}:activated",
                    trace_id=trace_id,
                    audit_event_id=membership.transition.audit_event_id,
                    payload={
                        "state": "active",
                        "role": invitation.intended_role,
                        "reasonCode": "invitation_accepted",
                        "authorityGeneration": authority_generation,
                    },
                    origin_type="authenticated_user",
                )
            )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=invitation.workspace_id,
                object_id=invitation.invitation_id,
                object_type="workspace_invitation",
                operation="accept_invitation",
                metadata={
                    "state": "accepted",
                    "membershipId": str(membership.membership.membership_id),
                    "membershipCreated": created,
                    "authorityGeneration": authority_generation,
                },
            )
        )
        return AcceptanceResult(membership, duplicate=not created)

    async def decline(
        self,
        *,
        principal: Principal,
        invitation_id: uuid.UUID,
        raw_token: str,
        idempotency_key: str,
    ) -> InvitationView:
        _idempotency_key(idempotency_key)
        invitation, current, token_secret = await self._credential_view(invitation_id, raw_token)
        self._require_recipient(principal, invitation)
        workspace = await self.session.get(Workspace, invitation.workspace_id)
        if workspace is None:
            raise CollaborationNotFoundError()
        request_digest = _digest(
            {
                "invitationId": str(invitation_id),
                "tokenHash": token_secret.token_hash,
                "actorUserId": str(principal.user_id),
            }
        )
        replay = await self._request_replay(
            actor_user_id=principal.user_id,
            workspace_id=invitation.workspace_id,
            operation="invitation.decline",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            view = await self.get(invitation_id, workspace_id=invitation.workspace_id)
            if view is None:
                raise CollaborationNotFoundError()
            return view
        if current.current_state != "pending":
            raise CollaborationNotFoundError()
        now = self._now()
        if _aware_utc(invitation.expires_at) <= now:
            await self._append_invitation_transition(
                workspace=workspace,
                invitation=invitation,
                previous=current,
                target_state="expired",
                actor_user_id=principal.user_id,
                reason_code="invitation_expired",
                result_membership_id=None,
            )
            raise InvitationExpiredError(transition_persisted=True)
        transition = await self._append_invitation_transition(
            workspace=workspace,
            invitation=invitation,
            previous=current,
            target_state="declined",
            actor_user_id=principal.user_id,
            reason_code="invitation_declined",
            result_membership_id=None,
        )
        self.session.add(
            self._request_identity(
                actor_user_id=principal.user_id,
                workspace_id=invitation.workspace_id,
                operation="invitation.decline",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_kind="workspace_invitation",
                result_id=invitation_id,
                trace_id=transition.trace_id,
                now=now,
            )
        )
        await self.session.flush()
        return InvitationView(invitation, transition, "declined")

    async def revoke(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        invitation_id: uuid.UUID,
        idempotency_key: str,
    ) -> InvitationView:
        workspace, _ = await self.memberships.require_owner(
            principal=principal, workspace_id=workspace_id
        )
        _idempotency_key(idempotency_key)
        request_digest = _digest(
            {"workspaceId": str(workspace_id), "invitationId": str(invitation_id)}
        )
        replay = await self._request_replay(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="invitation.revoke",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            view = await self.get(invitation_id, workspace_id=workspace_id)
            if view is None:
                raise CollaborationNotFoundError()
            return view
        view = await self._require_pending(invitation_id, workspace_id)
        now = self._now()
        if _aware_utc(view.invitation.expires_at) <= now:
            await self._append_invitation_transition(
                workspace=workspace,
                invitation=view.invitation,
                previous=view.transition,
                target_state="expired",
                actor_user_id=principal.user_id,
                reason_code="invitation_expired",
                result_membership_id=None,
            )
            raise InvitationExpiredError(transition_persisted=True)
        transition = await self._append_invitation_transition(
            workspace=workspace,
            invitation=view.invitation,
            previous=view.transition,
            target_state="revoked",
            actor_user_id=principal.user_id,
            reason_code="invitation_revoked",
            result_membership_id=None,
        )
        self.session.add(
            self._request_identity(
                actor_user_id=principal.user_id,
                workspace_id=workspace_id,
                operation="invitation.revoke",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_kind="workspace_invitation",
                result_id=invitation_id,
                trace_id=transition.trace_id,
                now=now,
            )
        )
        await self.session.flush()
        return InvitationView(view.invitation, transition, "revoked")

    async def list_for_workspace(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        limit: int = PAGE_DEFAULT,
        offset: int = 0,
    ) -> list[InvitationView]:
        await self.memberships.require_owner(principal=principal, workspace_id=workspace_id)
        _pagination(limit, offset)
        latest = (
            select(func.max(WorkspaceInvitationTransition.sequence))
            .where(WorkspaceInvitationTransition.invitation_id == WorkspaceInvitation.invitation_id)
            .correlate(WorkspaceInvitation)
            .scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(WorkspaceInvitation, WorkspaceInvitationTransition)
                .join(
                    WorkspaceInvitationTransition,
                    (
                        WorkspaceInvitationTransition.invitation_id
                        == WorkspaceInvitation.invitation_id
                    )
                    & (WorkspaceInvitationTransition.sequence == latest),
                )
                .where(WorkspaceInvitation.workspace_id == workspace_id)
                .order_by(WorkspaceInvitation.created_at.desc(), WorkspaceInvitation.invitation_id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        now = self._now()
        return [
            InvitationView(
                row[0],
                row[1],
                cast(
                    InvitationState,
                    "expired"
                    if row[1].current_state == "pending" and _aware_utc(row[0].expires_at) <= now
                    else row[1].current_state,
                ),
            )
            for row in rows
        ]

    async def get(
        self, invitation_id: uuid.UUID, *, workspace_id: uuid.UUID
    ) -> InvitationView | None:
        invitation = await self.session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.invitation_id == invitation_id,
                WorkspaceInvitation.workspace_id == workspace_id,
            )
        )
        if invitation is None:
            return None
        transition = await self._latest_transition(invitation_id)
        if transition is None:
            raise CollaborationConflictError("Invitation lifecycle evidence is incomplete.")
        effective = cast(
            InvitationState,
            "expired"
            if transition.current_state == "pending"
            and _aware_utc(invitation.expires_at) <= self._now()
            else transition.current_state,
        )
        return InvitationView(invitation, transition, effective)

    async def record_delivery(
        self,
        *,
        invitation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        secret_sequence: int,
        channel: DeliveryChannel,
        outcome: DeliveryOutcome,
        trace_id: uuid.UUID,
        failure_code: str | None = None,
    ) -> WorkspaceInvitationDeliveryAttempt:
        sequence = await self.session.scalar(
            select(func.max(WorkspaceInvitationDeliveryAttempt.sequence)).where(
                WorkspaceInvitationDeliveryAttempt.invitation_id == invitation_id
            )
        )
        attempt_sequence = 0 if sequence is None else sequence + 1
        attempt = WorkspaceInvitationDeliveryAttempt(
            attempt_id=uuid.uuid5(invitation_id, f"delivery:{attempt_sequence}"),
            invitation_id=invitation_id,
            workspace_id=workspace_id,
            sequence=attempt_sequence,
            secret_sequence=secret_sequence,
            channel=channel,
            outcome=outcome,
            failure_code=failure_code,
            trace_id=trace_id,
            recorded_at=self._now(),
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def _append_invitation_transition(
        self,
        *,
        workspace: Workspace,
        invitation: WorkspaceInvitation,
        previous: WorkspaceInvitationTransition,
        target_state: InvitationState,
        actor_user_id: uuid.UUID,
        reason_code: str,
        result_membership_id: uuid.UUID | None,
    ) -> WorkspaceInvitationTransition:
        trace_id = uuid.uuid4()
        now = self._now()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(actor_user_id),
                actor_type="user",
                user_id=actor_user_id,
                workspace_id=workspace.id,
                object_id=invitation.invitation_id,
                object_type="workspace_invitation",
                operation=f"{target_state}_invitation",
                metadata={"priorState": previous.current_state},
            )
        )
        audit = self.memberships._audit(
            workspace_id=workspace.id,
            actor_user_id=actor_user_id,
            subject_kind="workspace_invitation",
            subject_id=invitation.invitation_id,
            action=f"invitation.{target_state}",
            reason_code=reason_code,
            trace_id=trace_id,
            metadata={"state": target_state, "role": invitation.intended_role},
            recorded_at=now,
        )
        transition = WorkspaceInvitationTransition(
            transition_id=uuid.uuid5(invitation.invitation_id, f"transition:{target_state}"),
            invitation_id=invitation.invitation_id,
            workspace_id=workspace.id,
            sequence=previous.sequence + 1,
            previous_state=previous.current_state,
            current_state=target_state,
            reason_code=reason_code,
            result_membership_id=result_membership_id,
            actor_user_id=actor_user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add_all((audit, transition))
        await self.session.flush()
        await self._record_event(
            workspace=workspace,
            event_type=f"invitation.{target_state}",
            invitation=invitation,
            actor_user_id=actor_user_id,
            state=target_state,
            reason_code=reason_code,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            membership_id=result_membership_id,
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.invitation",
                actor_id=str(actor_user_id),
                actor_type="user",
                user_id=actor_user_id,
                workspace_id=workspace.id,
                object_id=invitation.invitation_id,
                object_type="workspace_invitation",
                operation=f"{target_state}_invitation",
                metadata={"state": target_state, "reasonCode": reason_code},
            )
        )
        return transition

    async def _record_event(
        self,
        *,
        workspace: Workspace,
        event_type: str,
        invitation: WorkspaceInvitation,
        actor_user_id: uuid.UUID,
        state: InvitationState,
        reason_code: str,
        trace_id: uuid.UUID,
        audit_event_id: uuid.UUID,
        membership_id: uuid.UUID | None = None,
        authority_generation: int | None = None,
    ) -> None:
        payload: dict[str, JsonValue] = {
            "state": state,
            "role": invitation.intended_role,
            "reasonCode": reason_code,
        }
        if membership_id is not None:
            payload["membershipId"] = str(membership_id)
        if authority_generation is not None:
            payload["authorityGeneration"] = authority_generation
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=workspace.owner_id,
                workspace_id=workspace.id,
                canvas_id=None,
                subject_id=invitation.invitation_id,
                actor_user_id=actor_user_id,
                source_identity=f"invitation:{invitation.invitation_id}:{state}",
                trace_id=trace_id,
                audit_event_id=audit_event_id,
                related_id=membership_id,
                payload=payload,
                origin_type="authenticated_user",
            )
        )

    async def _credential_view(
        self, invitation_id: uuid.UUID, raw_token: str
    ) -> tuple[
        WorkspaceInvitation,
        WorkspaceInvitationTransition,
        WorkspaceInvitationSecretVersion,
    ]:
        if not 20 <= len(raw_token) <= 512:
            raise CollaborationNotFoundError()
        secret = await self.session.scalar(
            select(WorkspaceInvitationSecretVersion).where(
                WorkspaceInvitationSecretVersion.invitation_id == invitation_id,
                WorkspaceInvitationSecretVersion.token_hash == self._token_hash(raw_token),
            )
        )
        invitation = await self.session.get(WorkspaceInvitation, invitation_id)
        current = await self._latest_transition(invitation_id)
        latest_secret = await self._latest_secret(invitation_id)
        if (
            invitation is None
            or current is None
            or secret is None
            or latest_secret is None
            or secret.sequence != latest_secret.sequence
        ):
            raise CollaborationNotFoundError()
        return invitation, current, secret

    async def _require_pending(
        self, invitation_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> InvitationView:
        view = await self.get(invitation_id, workspace_id=workspace_id)
        if view is None or view.transition.current_state != "pending":
            raise CollaborationNotFoundError()
        return view

    async def _expire_or_continue(
        self, view: InvitationView, actor_user_id: uuid.UUID, now: datetime
    ) -> None:
        if _aware_utc(view.invitation.expires_at) > now:
            return
        workspace = await self.session.get(Workspace, view.invitation.workspace_id)
        if workspace is None:
            raise CollaborationNotFoundError()
        await self._append_invitation_transition(
            workspace=workspace,
            invitation=view.invitation,
            previous=view.transition,
            target_state="expired",
            actor_user_id=actor_user_id,
            reason_code="invitation_expired",
            result_membership_id=None,
        )
        raise InvitationExpiredError(transition_persisted=True)

    async def _latest_transition(
        self, invitation_id: uuid.UUID
    ) -> WorkspaceInvitationTransition | None:
        return cast(
            WorkspaceInvitationTransition | None,
            await self.session.scalar(
                select(WorkspaceInvitationTransition)
                .where(WorkspaceInvitationTransition.invitation_id == invitation_id)
                .order_by(WorkspaceInvitationTransition.sequence.desc())
                .limit(1)
            ),
        )

    async def _latest_secret(
        self, invitation_id: uuid.UUID
    ) -> WorkspaceInvitationSecretVersion | None:
        return cast(
            WorkspaceInvitationSecretVersion | None,
            await self.session.scalar(
                select(WorkspaceInvitationSecretVersion)
                .where(WorkspaceInvitationSecretVersion.invitation_id == invitation_id)
                .order_by(WorkspaceInvitationSecretVersion.sequence.desc())
                .limit(1)
            ),
        )

    async def _pending_for_recipient(
        self, workspace_id: uuid.UUID, recipient_digest: str
    ) -> WorkspaceInvitation | None:
        latest = (
            select(func.max(WorkspaceInvitationTransition.sequence))
            .where(WorkspaceInvitationTransition.invitation_id == WorkspaceInvitation.invitation_id)
            .correlate(WorkspaceInvitation)
            .scalar_subquery()
        )
        return cast(
            WorkspaceInvitation | None,
            await self.session.scalar(
                select(WorkspaceInvitation)
                .join(
                    WorkspaceInvitationTransition,
                    (
                        WorkspaceInvitationTransition.invitation_id
                        == WorkspaceInvitation.invitation_id
                    )
                    & (WorkspaceInvitationTransition.sequence == latest),
                )
                .where(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitation.recipient_digest == recipient_digest,
                    WorkspaceInvitationTransition.current_state == "pending",
                )
            ),
        )

    async def _pending_count(self, workspace_id: uuid.UUID) -> int:
        latest = (
            select(func.max(WorkspaceInvitationTransition.sequence))
            .where(WorkspaceInvitationTransition.invitation_id == WorkspaceInvitation.invitation_id)
            .correlate(WorkspaceInvitation)
            .scalar_subquery()
        )
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(WorkspaceInvitation)
                .join(
                    WorkspaceInvitationTransition,
                    (
                        WorkspaceInvitationTransition.invitation_id
                        == WorkspaceInvitation.invitation_id
                    )
                    & (WorkspaceInvitationTransition.sequence == latest),
                )
                .where(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitationTransition.current_state == "pending",
                    WorkspaceInvitation.expires_at > self._now(),
                )
            )
            or 0
        )

    async def _active_membership_count(self, workspace_id: uuid.UUID) -> int:
        latest = (
            select(func.max(WorkspaceMembershipTransition.sequence))
            .where(WorkspaceMembershipTransition.membership_id == WorkspaceMembership.membership_id)
            .correlate(WorkspaceMembership)
            .scalar_subquery()
        )
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .join(
                    WorkspaceMembershipTransition,
                    (
                        WorkspaceMembershipTransition.membership_id
                        == WorkspaceMembership.membership_id
                    )
                    & (WorkspaceMembershipTransition.sequence == latest),
                )
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembershipTransition.current_state == "active",
                )
            )
            or 0
        )

    async def _active_workspace_count(self, user_id: uuid.UUID) -> int:
        latest = (
            select(func.max(WorkspaceMembershipTransition.sequence))
            .where(WorkspaceMembershipTransition.membership_id == WorkspaceMembership.membership_id)
            .correlate(WorkspaceMembership)
            .scalar_subquery()
        )
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
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
                    WorkspaceMembershipTransition.current_state == "active",
                )
            )
            or 0
        )

    async def _request_replay(
        self,
        *,
        actor_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        operation: str,
        idempotency_key: str,
        request_digest: str,
    ) -> CollaborationRequestIdentity | None:
        existing = await self.session.scalar(
            select(CollaborationRequestIdentity).where(
                CollaborationRequestIdentity.actor_user_id == actor_user_id,
                CollaborationRequestIdentity.workspace_id == workspace_id,
                CollaborationRequestIdentity.operation == operation,
                CollaborationRequestIdentity.idempotency_key == idempotency_key,
            )
        )
        if existing is not None and existing.request_digest != request_digest:
            raise CollaborationConflictError("Idempotency key was reused for another request.")
        return existing

    def _request_identity(
        self,
        *,
        actor_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        operation: str,
        idempotency_key: str,
        request_digest: str,
        result_kind: str,
        result_id: uuid.UUID,
        trace_id: uuid.UUID,
        now: datetime,
    ) -> CollaborationRequestIdentity:
        return CollaborationRequestIdentity(
            request_id=uuid.uuid5(
                workspace_id,
                f"{actor_user_id}:{operation}:{idempotency_key}",
            ),
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_kind=result_kind,
            result_id=result_id,
            trace_id=trace_id,
            created_at=now,
        )

    async def _authority(
        self, workspace_id: uuid.UUID, trace_id: uuid.UUID, now: datetime
    ) -> WorkspaceAuthorityVersion:
        return await self.memberships._ensure_authority(workspace_id, trace_id, now)

    async def _increment_authority(
        self, workspace_id: uuid.UUID, trace_id: uuid.UUID, now: datetime
    ) -> int:
        await self._authority(workspace_id, trace_id, now)
        generation = await self.session.scalar(
            update(WorkspaceAuthorityVersion)
            .where(WorkspaceAuthorityVersion.workspace_id == workspace_id)
            .values(
                authority_generation=WorkspaceAuthorityVersion.authority_generation + 1,
                last_trace_id=trace_id,
                updated_at=now,
            )
            .returning(WorkspaceAuthorityVersion.authority_generation)
        )
        if generation is None:
            raise CollaborationConflictError("Workspace authority state is unavailable.")
        return generation

    def _require_recipient(self, principal: Principal, invitation: WorkspaceInvitation) -> None:
        try:
            normalized = normalize_email(principal.email)
        except AuthenticationError as exc:
            raise CollaborationNotFoundError() from exc
        if (
            normalized != invitation.recipient_email_normalized
            or self._recipient_digest(normalized) != invitation.recipient_digest
            or (
                invitation.recipient_user_id is not None
                and invitation.recipient_user_id != principal.user_id
            )
        ):
            raise CollaborationNotFoundError()

    def _recipient_digest(self, normalized_email: str) -> str:
        return hmac.new(
            self.settings.invitation_secret.encode("utf-8"),
            f"recipient:{normalized_email}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _token_hash(self, raw_token: str) -> str:
        return hmac.new(
            self.settings.invitation_secret.encode("utf-8"),
            f"token:{raw_token}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _now(self) -> datetime:
        return _aware_utc(self._now_factory())


def mask_email(normalized_email: str) -> str:
    local, domain = normalized_email.split("@", maxsplit=1)
    return f"{local[:1]}***@{domain}"


def _invitation_role(value: str) -> InvitationRole:
    if value not in INVITATION_ROLES:
        raise CollaborationValidationError("Invitation role is unsupported.")
    return cast(InvitationRole, value)


def _idempotency_key(value: str) -> None:
    if not 8 <= len(value) <= 128 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
        for character in value
    ):
        raise CollaborationValidationError("Idempotency key is invalid.")


def _pagination(limit: int, offset: int) -> None:
    if not 1 <= limit <= PAGE_MAX or not 0 <= offset <= 100_000:
        raise CollaborationValidationError("Pagination is outside its bounds.")


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "COLLABORATION_POLICY_VERSION",
    "INVITATION_DEFAULT_DAYS",
    "INVITATION_MAX_DAYS",
    "MEMBERSHIP_LIMIT_PER_WORKSPACE",
    "PAGE_DEFAULT",
    "PAGE_MAX",
    "PENDING_INVITATION_LIMIT_PER_WORKSPACE",
    "WORKSPACE_LIMIT_PER_USER",
    "AcceptanceResult",
    "CollaborationConflictError",
    "CollaborationError",
    "CollaborationLimitError",
    "CollaborationNotFoundError",
    "CollaborationValidationError",
    "InvitationExpiredError",
    "InvitationService",
    "InvitationView",
    "IssuedInvitation",
    "MembershipService",
    "MembershipView",
    "mask_email",
]
