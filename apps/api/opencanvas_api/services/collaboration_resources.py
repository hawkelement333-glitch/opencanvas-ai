from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    BoundedAgentIdentity,
    BoundedAgentLifecycleState,
    CanonicalObject,
    Canvas,
    CollaborationAuditEvent,
    CollaborationAuthoritySnapshot,
    CollaborationOwnershipTransfer,
    CollaborationOwnershipTransferTransition,
    CollaborationResource,
    CollaborationResourceOwnershipTransition,
    CollaborationResourceShare,
    CollaborationResourceShareTransition,
    CollaborationRevocationFence,
    ControlledWorkflowDefinition,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembershipTransition,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration import (
    COLLABORATION_POLICY_VERSION,
    CollaborationConflictError,
    CollaborationNotFoundError,
    CollaborationValidationError,
    MembershipService,
    MembershipView,
)
from opencanvas_api.services.collaboration_authority import (
    ROLE_PERMISSION_CEILINGS,
    CollaborationAction,
    CollaborationAuthorizationService,
    CollaborationPermission,
    CollaborationRole,
)
from opencanvas_api.services.collaboration_management import (
    _audit,
    _increment_authority,
    _request_identity,
    _request_replay,
    _validate_idempotency_key,
)
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import CompleteTraceInput, StartTraceInput, TraceService

SHARE_BATCH_MAX = 50
BULK_REVOCATION_MAX = 50
SHARES_PER_RESOURCE_MAX = 500
SHARED_RESOURCES_PER_WORKSPACE_MAX = 10_000
SHARE_PAGE_DEFAULT = 50
SHARE_PAGE_MAX = 100
TRANSFER_DEFAULT_HOURS = 48
TRANSFER_MAX_DAYS = 7


class ShareResourceKind(StrEnum):
    CANVAS = "canvas"
    CANONICAL_OBJECT = "canonical_object"
    WORKFLOW = "workflow"
    AGENT = "agent"


class ShareAccessLevel(StrEnum):
    VIEW = "view"
    CONTRIBUTE = "contribute"
    MANAGE = "manage"


class ShareAudienceKind(StrEnum):
    WORKSPACE = "workspace"
    MEMBERSHIP = "membership"


class ResourceVisibilityPolicy(StrEnum):
    PRIVATE = "private"
    INHERIT = "inherit"
    WORKSPACE_VISIBLE = "workspace_visible"


class OwnershipTransferKind(StrEnum):
    WORKSPACE = "workspace"
    RESOURCE = "resource"


class OwnershipTransferState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class AuthorityBoundary(StrEnum):
    CLAIM = "claim"
    SERVICE_CALL = "service_call"
    TOOL_CALL = "tool_call"
    RETRY = "retry"
    EFFECT = "effect"
    COMPENSATION = "compensation"
    EXPORT = "export"
    PUBLICATION = "publication"
    SHARE_DECISION = "share_decision"
    OWNERSHIP_DECISION = "ownership_decision"


_ACCESS_ORDER = {
    ShareAccessLevel.VIEW: 0,
    ShareAccessLevel.CONTRIBUTE: 1,
    ShareAccessLevel.MANAGE: 2,
}

_VIEW_PERMISSION = {
    ShareResourceKind.CANVAS: CollaborationPermission.CANVAS_VIEW,
    ShareResourceKind.CANONICAL_OBJECT: CollaborationPermission.RESOURCE_VIEW,
    ShareResourceKind.WORKFLOW: CollaborationPermission.WORKFLOW_VIEW,
    ShareResourceKind.AGENT: CollaborationPermission.AGENT_VIEW,
}
_EDIT_PERMISSION = {
    ShareResourceKind.CANVAS: CollaborationPermission.CANVAS_EDIT,
    ShareResourceKind.CANONICAL_OBJECT: CollaborationPermission.RESOURCE_EDIT,
    ShareResourceKind.WORKFLOW: CollaborationPermission.WORKFLOW_EDIT,
    ShareResourceKind.AGENT: CollaborationPermission.AGENT_EDIT,
}
_SHARE_PERMISSION = {
    ShareResourceKind.CANVAS: CollaborationPermission.CANVAS_SHARE,
    ShareResourceKind.CANONICAL_OBJECT: CollaborationPermission.RESOURCE_SHARE,
    ShareResourceKind.WORKFLOW: CollaborationPermission.WORKFLOW_SHARE,
    ShareResourceKind.AGENT: CollaborationPermission.AGENT_SHARE,
}


@dataclass(frozen=True, slots=True)
class ShareTarget:
    resource_kind: ShareResourceKind
    resource_id: uuid.UUID
    audience_kind: ShareAudienceKind
    audience_membership_id: uuid.UUID | None
    access_level: ShareAccessLevel
    expires_in_days: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    resource: CollaborationResource
    ownership: CollaborationResourceOwnershipTransition


@dataclass(frozen=True, slots=True)
class ShareRecord:
    share: CollaborationResourceShare
    transition: CollaborationResourceShareTransition
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class TransferRecord:
    transfer: CollaborationOwnershipTransfer
    transition: CollaborationOwnershipTransferTransition
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ResourceAccessDecision:
    allowed: bool
    reason_code: str
    permission: CollaborationPermission
    membership_id: uuid.UUID | None
    role: CollaborationRole | None
    authority_generation: int | None
    resource: ResourceRecord | None
    share: ShareRecord | None
    inherited_from_canvas_id: uuid.UUID | None = None


class ResourceRegistryService:
    """Resolve database-verified typed collaboration resources."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        *,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind | str,
        resource_id: uuid.UUID,
    ) -> ResourceRecord | None:
        try:
            kind = ShareResourceKind(resource_kind)
        except ValueError:
            return None
        resource = await self.session.get(
            CollaborationResource,
            {
                "resource_id": resource_id,
                "workspace_id": workspace_id,
                "resource_kind": kind.value,
            },
        )
        if resource is None or not await self._target_is_current(resource):
            return None
        ownership = await self.session.scalar(
            select(CollaborationResourceOwnershipTransition)
            .where(
                CollaborationResourceOwnershipTransition.workspace_id == workspace_id,
                CollaborationResourceOwnershipTransition.resource_kind == kind.value,
                CollaborationResourceOwnershipTransition.resource_id == resource_id,
            )
            .order_by(CollaborationResourceOwnershipTransition.sequence.desc())
            .limit(1)
        )
        return ResourceRecord(resource, ownership) if ownership is not None else None

    async def _target_is_current(self, resource: CollaborationResource) -> bool:
        kind = ShareResourceKind(resource.resource_kind)
        if kind is ShareResourceKind.CANVAS:
            return (
                await self.session.scalar(
                    select(Canvas.id).where(
                        Canvas.id == resource.resource_id,
                        Canvas.workspace_id == resource.workspace_id,
                    )
                )
                is not None
            )
        if kind is ShareResourceKind.CANONICAL_OBJECT:
            return (
                await self.session.scalar(
                    select(CanonicalObject.id).where(
                        CanonicalObject.id == resource.resource_id,
                        CanonicalObject.workspace_id == resource.workspace_id,
                        CanonicalObject.lifecycle_state.in_(("created", "active")),
                    )
                )
                is not None
            )
        if kind is ShareResourceKind.WORKFLOW:
            return (
                await self.session.scalar(
                    select(ControlledWorkflowDefinition.definition_id).where(
                        ControlledWorkflowDefinition.definition_id == resource.resource_id,
                        ControlledWorkflowDefinition.workspace_id == resource.workspace_id,
                        ControlledWorkflowDefinition.canvas_id == resource.canvas_id,
                    )
                )
                is not None
            )
        latest = (
            select(func.max(BoundedAgentLifecycleState.sequence))
            .where(BoundedAgentLifecycleState.agent_id == BoundedAgentIdentity.agent_id)
            .correlate(BoundedAgentIdentity)
            .scalar_subquery()
        )
        state = await self.session.scalar(
            select(BoundedAgentLifecycleState.state)
            .join(
                BoundedAgentIdentity,
                BoundedAgentIdentity.agent_id == BoundedAgentLifecycleState.agent_id,
            )
            .where(
                BoundedAgentIdentity.agent_id == resource.resource_id,
                BoundedAgentIdentity.workspace_id == resource.workspace_id,
                BoundedAgentIdentity.canvas_id == resource.canvas_id,
                BoundedAgentLifecycleState.sequence == latest,
            )
        )
        return state is not None and state != "retired"


class SharingService:
    """Typed, bounded, append-only sharing and visibility evaluation."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.resources = ResourceRegistryService(session)
        self.memberships = MembershipService(session, now_factory=self._now_factory)
        self.authorization = CollaborationAuthorizationService(session)
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def list_shares(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        limit: int = SHARE_PAGE_DEFAULT,
        offset: int = 0,
    ) -> list[ShareRecord]:
        if not 1 <= limit <= SHARE_PAGE_MAX or offset < 0:
            raise CollaborationValidationError()
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=CollaborationAction.SHARE_LIST,
        )
        if not decision.allowed:
            raise CollaborationNotFoundError()
        rows = (
            await self.session.scalars(
                select(CollaborationResourceShare)
                .where(CollaborationResourceShare.workspace_id == workspace_id)
                .order_by(
                    CollaborationResourceShare.created_at.desc(),
                    CollaborationResourceShare.share_id,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        records: list[ShareRecord] = []
        for share in rows:
            transition = await self._current_share(share.share_id, workspace_id)
            if transition is None:
                raise CollaborationConflictError()
            records.append(ShareRecord(share, transition))
        return records

    async def create(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        targets: Sequence[ShareTarget],
        idempotency_key: str,
    ) -> list[ShareRecord]:
        _validate_idempotency_key(idempotency_key)
        if not 1 <= len(targets) <= SHARE_BATCH_MAX:
            raise CollaborationValidationError()
        normalized = sorted(
            targets,
            key=lambda item: (
                item.resource_kind.value,
                str(item.resource_id),
                item.audience_kind.value,
                str(item.audience_membership_id or ""),
                item.access_level.value,
            ),
        )
        if len(
            {
                (
                    item.resource_kind,
                    item.resource_id,
                    item.audience_kind,
                    item.audience_membership_id,
                )
                for item in normalized
            }
        ) != len(normalized):
            raise CollaborationValidationError()
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "targets": [
                    {
                        "resourceKind": item.resource_kind.value,
                        "resourceId": str(item.resource_id),
                        "audienceKind": item.audience_kind.value,
                        "audienceMembershipId": (
                            str(item.audience_membership_id)
                            if item.audience_membership_id
                            else None
                        ),
                        "accessLevel": item.access_level.value,
                        "expiresInDays": item.expires_in_days,
                    }
                    for item in normalized
                ],
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="share.create",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            rows = (
                await self.session.scalars(
                    select(CollaborationResourceShare).where(
                        CollaborationResourceShare.workspace_id == workspace_id,
                        CollaborationResourceShare.creation_request_id == replay.result_id,
                    )
                )
            ).all()
            if not rows:
                raise CollaborationConflictError()
            result: list[ShareRecord] = []
            for share in rows:
                transition = await self._current_share(share.share_id, workspace_id)
                if transition is None:
                    raise CollaborationConflictError()
                result.append(ShareRecord(share, transition, duplicate=True))
            return result

        resolved: list[
            tuple[
                ShareTarget,
                ResourceRecord,
                MembershipView | None,
                CollaborationRole,
                uuid.UUID,
            ]
        ] = []
        actor_membership_id: uuid.UUID | None = None
        actor_role: CollaborationRole | None = None
        for target in normalized:
            permission = _SHARE_PERMISSION[target.resource_kind]
            decision = await self.authorization.evaluate_permission(
                principal=principal,
                workspace_id=workspace_id,
                permission=permission,
                action=CollaborationAction.SHARE_CREATE,
            )
            if not decision.allowed or decision.membership_id is None or decision.role is None:
                raise CollaborationNotFoundError()
            resource = await self.resources.get(
                workspace_id=workspace_id,
                resource_kind=target.resource_kind,
                resource_id=target.resource_id,
            )
            if resource is None or not self._can_manage_resource(
                resource, decision.membership_id, decision.role
            ):
                raise CollaborationNotFoundError()
            audience: MembershipView | None = None
            if target.audience_kind is ShareAudienceKind.MEMBERSHIP:
                if target.audience_membership_id is None:
                    raise CollaborationValidationError()
                audience = await self.memberships.get(
                    membership_id=target.audience_membership_id,
                    workspace_id=workspace_id,
                )
                if audience is None or audience.transition.current_state != "active":
                    raise CollaborationNotFoundError()
                recipient_role = CollaborationRole(audience.transition.current_role)
                required = _permission_for_level(target.resource_kind, target.access_level)
                if required not in ROLE_PERMISSION_CEILINGS[recipient_role]:
                    raise CollaborationNotFoundError()
            elif target.audience_membership_id is not None:
                raise CollaborationValidationError()
            if target.expires_in_days is not None and not 1 <= target.expires_in_days <= 30:
                raise CollaborationValidationError()
            actor_membership_id = decision.membership_id
            actor_role = decision.role
            resolved.append((target, resource, audience, decision.role, decision.membership_id))
        if actor_membership_id is None or actor_role is None:
            raise CollaborationValidationError()
        active_count = await self.session.scalar(
            select(func.count())
            .select_from(CollaborationResourceShare)
            .join(
                CollaborationResourceShareTransition,
                CollaborationResourceShareTransition.share_id
                == CollaborationResourceShare.share_id,
            )
            .where(
                CollaborationResourceShare.workspace_id == workspace_id,
                CollaborationResourceShareTransition.sequence
                == (
                    select(func.max(CollaborationResourceShareTransition.sequence))
                    .where(
                        CollaborationResourceShareTransition.share_id
                        == CollaborationResourceShare.share_id
                    )
                    .correlate(CollaborationResourceShare)
                    .scalar_subquery()
                ),
                CollaborationResourceShareTransition.current_state == "active",
            )
        )
        if (active_count or 0) + len(resolved) > SHARED_RESOURCES_PER_WORKSPACE_MAX:
            raise CollaborationValidationError()

        now = _aware(self._now_factory())
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.resource_sharing",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=request_id,
                object_type="resource_share_request",
                operation="share_create",
                metadata={"targetCount": len(resolved)},
            )
        )
        generation = await _increment_authority(
            self.session,
            workspace_id=workspace_id,
            trace_id=trace_id,
            now=now,
        )
        records: list[ShareRecord] = []
        audit_ids: list[uuid.UUID] = []
        for target, resource, audience, _, _ in resolved:
            existing = await self.session.scalar(
                select(CollaborationResourceShare).where(
                    CollaborationResourceShare.workspace_id == workspace_id,
                    CollaborationResourceShare.resource_kind == target.resource_kind.value,
                    CollaborationResourceShare.resource_id == target.resource_id,
                    CollaborationResourceShare.audience_key
                    == _audience_key(
                        target.audience_kind,
                        workspace_id,
                        target.audience_membership_id,
                    ),
                )
            )
            previous = (
                await self._current_share(existing.share_id, workspace_id)
                if existing is not None
                else None
            )
            if previous is not None and previous.current_state == "active":
                raise CollaborationConflictError()
            share_id = existing.share_id if existing is not None else uuid.uuid4()
            audit = _audit(
                workspace_id=workspace_id,
                actor_user_id=principal.user_id,
                subject_kind="resource_share",
                subject_id=share_id,
                action="share.create",
                reason_code=(
                    "resource_share_reactivated"
                    if existing is not None
                    else "resource_share_created"
                ),
                trace_id=trace_id,
                metadata={
                    "resourceKind": target.resource_kind.value,
                    "resourceId": str(target.resource_id),
                    "audienceKind": target.audience_kind.value,
                    "accessLevel": target.access_level.value,
                },
                now=now,
            )
            self.session.add(audit)
            await self.session.flush()
            audit_ids.append(audit.audit_event_id)
            if existing is None:
                existing = CollaborationResourceShare(
                    share_id=share_id,
                    workspace_id=workspace_id,
                    resource_id=target.resource_id,
                    resource_kind=target.resource_kind.value,
                    audience_kind=target.audience_kind.value,
                    audience_key=_audience_key(
                        target.audience_kind,
                        workspace_id,
                        target.audience_membership_id,
                    ),
                    audience_membership_id=(
                        audience.membership.membership_id if audience else None
                    ),
                    audience_user_id=audience.membership.user_id if audience else None,
                    created_by_membership_id=actor_membership_id,
                    created_by_user_id=principal.user_id,
                    collaboration_policy_version=COLLABORATION_POLICY_VERSION,
                    creation_request_id=request_id,
                    request_digest=request_digest,
                    creation_trace_id=trace_id,
                    creation_audit_event_id=audit.audit_event_id,
                    created_at=now,
                )
                self.session.add(existing)
                await self.session.flush()
            transition = CollaborationResourceShareTransition(
                transition_id=uuid.uuid4(),
                share_id=share_id,
                workspace_id=workspace_id,
                sequence=0 if previous is None else previous.sequence + 1,
                previous_state=None if previous is None else previous.current_state,
                current_state="active",
                access_level=target.access_level.value,
                expires_at=(
                    now + timedelta(days=target.expires_in_days) if target.expires_in_days else None
                ),
                authority_generation=generation,
                actor_user_id=principal.user_id,
                actor_membership_id=actor_membership_id,
                reason_code=(
                    "resource_share_reactivated"
                    if previous is not None
                    else "resource_share_created"
                ),
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                recorded_at=now,
            )
            self.session.add(transition)
            await self.session.flush()
            await self._event(
                event_type=(
                    "resource.share.changed" if previous is not None else "resource.share.created"
                ),
                workspace_id=workspace_id,
                actor_user_id=principal.user_id,
                subject_id=share_id,
                related_id=target.resource_id,
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                generation=generation,
                payload={
                    "resourceKind": target.resource_kind.value,
                    "accessLevel": target.access_level.value,
                    "state": "active",
                    "audienceKind": target.audience_kind.value,
                },
                source=f"share:{share_id}:transition:{transition.sequence}",
                canvas_id=resource.resource.canvas_id,
            )
            records.append(ShareRecord(existing, transition))
        request = _request_identity(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="share.create",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_kind="resource_share_request",
            result_id=request_id,
            trace_id=trace_id,
            now=now,
        )
        self.session.add(request)
        await self._fence(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            actor_membership_id=actor_membership_id,
            previous_generation=generation - 1,
            generation=generation,
            reason_code="resource_shares_changed",
            trace_id=trace_id,
            audit_event_id=audit_ids[0],
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.resource_sharing",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=request_id,
                object_type="resource_share_request",
                operation="share_create",
                metadata={"targetCount": len(records), "authorityGeneration": generation},
            )
        )
        return records

    async def revoke(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        share_ids: Sequence[uuid.UUID],
        idempotency_key: str,
    ) -> list[ShareRecord]:
        _validate_idempotency_key(idempotency_key)
        unique_ids = tuple(dict.fromkeys(share_ids))
        if not 1 <= len(unique_ids) <= BULK_REVOCATION_MAX:
            raise CollaborationValidationError()
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "shareIds": sorted(str(value) for value in unique_ids),
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="share.revoke",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            rows: list[ShareRecord] = []
            for share_id in unique_ids:
                share = await self.session.get(CollaborationResourceShare, share_id)
                transition = await self._current_share(share_id, workspace_id)
                if share is None or transition is None:
                    raise CollaborationConflictError()
                rows.append(ShareRecord(share, transition, duplicate=True))
            return rows
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=(
                CollaborationAction.SHARE_REVOKE
                if len(unique_ids) == 1
                else CollaborationAction.SHARE_BULK_REVOKE
            ),
        )
        if not decision.allowed or decision.membership_id is None or decision.role is None:
            raise CollaborationNotFoundError()
        resolved: list[
            tuple[
                CollaborationResourceShare,
                CollaborationResourceShareTransition,
                ResourceRecord,
            ]
        ] = []
        for share_id in unique_ids:
            share = await self.session.scalar(
                select(CollaborationResourceShare).where(
                    CollaborationResourceShare.share_id == share_id,
                    CollaborationResourceShare.workspace_id == workspace_id,
                )
            )
            transition = await self._current_share(share_id, workspace_id)
            resource = (
                await self.resources.get(
                    workspace_id=workspace_id,
                    resource_kind=share.resource_kind,
                    resource_id=share.resource_id,
                )
                if share is not None
                else None
            )
            if (
                share is None
                or transition is None
                or resource is None
                or not self._can_manage_resource(resource, decision.membership_id, decision.role)
            ):
                raise CollaborationNotFoundError()
            if transition.current_state != "active":
                raise CollaborationConflictError()
            resolved.append((share, transition, resource))
        now = _aware(self._now_factory())
        trace_id = uuid.uuid4()
        request_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.resource_sharing",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=request_id,
                object_type="resource_share_request",
                operation="share_revoke",
                metadata={"targetCount": len(resolved)},
            )
        )
        generation = await _increment_authority(
            self.session,
            workspace_id=workspace_id,
            trace_id=trace_id,
            now=now,
        )
        results: list[ShareRecord] = []
        audit_ids: list[uuid.UUID] = []
        for share, previous, resource in resolved:
            audit = _audit(
                workspace_id=workspace_id,
                actor_user_id=principal.user_id,
                subject_kind="resource_share",
                subject_id=share.share_id,
                action="share.revoke",
                reason_code="resource_share_revoked",
                trace_id=trace_id,
                metadata={
                    "resourceKind": share.resource_kind,
                    "resourceId": str(share.resource_id),
                    "previousAccessLevel": previous.access_level,
                },
                now=now,
            )
            self.session.add(audit)
            await self.session.flush()
            audit_ids.append(audit.audit_event_id)
            transition = CollaborationResourceShareTransition(
                transition_id=uuid.uuid4(),
                share_id=share.share_id,
                workspace_id=workspace_id,
                sequence=previous.sequence + 1,
                previous_state="active",
                current_state="revoked",
                access_level=previous.access_level,
                expires_at=None,
                authority_generation=generation,
                actor_user_id=principal.user_id,
                actor_membership_id=decision.membership_id,
                reason_code="resource_share_revoked",
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                recorded_at=now,
            )
            self.session.add(transition)
            await self.session.flush()
            await self._event(
                event_type="resource.share.revoked",
                workspace_id=workspace_id,
                actor_user_id=principal.user_id,
                subject_id=share.share_id,
                related_id=share.resource_id,
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                generation=generation,
                payload={
                    "resourceKind": share.resource_kind,
                    "accessLevel": previous.access_level,
                    "state": "revoked",
                    "audienceKind": share.audience_kind,
                },
                source=f"share:{share.share_id}:transition:{transition.sequence}",
                canvas_id=resource.resource.canvas_id,
            )
            results.append(ShareRecord(share, transition))
        self.session.add(
            _request_identity(
                actor_user_id=principal.user_id,
                workspace_id=workspace_id,
                operation="share.revoke",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_kind="resource_share_request",
                result_id=request_id,
                trace_id=trace_id,
                now=now,
            )
        )
        await self._fence(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            previous_generation=generation - 1,
            generation=generation,
            reason_code=(
                "resource_share_revoked" if len(results) == 1 else "bulk_resource_shares_revoked"
            ),
            trace_id=trace_id,
            audit_event_id=audit_ids[0],
            share_id=results[0].share.share_id if len(results) == 1 else None,
        )
        if len(results) > 1:
            await self._event(
                event_type="revocation.bulk_completed",
                workspace_id=workspace_id,
                actor_user_id=principal.user_id,
                subject_id=request_id,
                related_id=None,
                trace_id=trace_id,
                audit_event_id=audit_ids[0],
                generation=generation,
                payload={"targetCount": len(results), "scopeKind": "share"},
                source=f"bulk-revocation:{request_id}",
                canvas_id=None,
            )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.resource_sharing",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=request_id,
                object_type="resource_share_request",
                operation="share_revoke",
                metadata={"targetCount": len(results), "authorityGeneration": generation},
            )
        )
        return results

    async def set_visibility(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind,
        resource_id: uuid.UUID,
        visibility_policy: ResourceVisibilityPolicy,
        idempotency_key: str,
    ) -> ResourceRecord:
        _validate_idempotency_key(idempotency_key)
        permission = _SHARE_PERMISSION[resource_kind]
        decision = await self.authorization.evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=permission,
            action=CollaborationAction.RESOURCE_VISIBILITY_CHANGE,
        )
        if not decision.allowed or decision.membership_id is None or decision.role is None:
            raise CollaborationNotFoundError()
        resource = await self.resources.get(
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
        )
        if resource is None or not self._can_manage_resource(
            resource, decision.membership_id, decision.role
        ):
            raise CollaborationNotFoundError()
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "resourceKind": resource_kind.value,
                "resourceId": str(resource_id),
                "visibilityPolicy": visibility_policy.value,
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="resource.visibility.change",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            replayed = await self.resources.get(
                workspace_id=workspace_id,
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            if replayed is None:
                raise CollaborationConflictError()
            return replayed
        if resource.ownership.visibility_policy == visibility_policy.value:
            raise CollaborationConflictError()
        now = _aware(self._now_factory())
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.resource_visibility",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=resource_id,
                object_type=resource_kind.value,
                operation="resource_visibility_change",
                metadata={"visibilityPolicy": visibility_policy.value},
            )
        )
        generation = await _increment_authority(
            self.session,
            workspace_id=workspace_id,
            trace_id=trace_id,
            now=now,
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="collaboration_resource",
            subject_id=resource_id,
            action="resource.visibility.change",
            reason_code="resource_visibility_changed",
            trace_id=trace_id,
            metadata={
                "resourceKind": resource_kind.value,
                "previousVisibilityPolicy": resource.ownership.visibility_policy,
                "visibilityPolicy": visibility_policy.value,
            },
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        transition = CollaborationResourceOwnershipTransition(
            transition_id=uuid.uuid4(),
            resource_id=resource_id,
            workspace_id=workspace_id,
            resource_kind=resource_kind.value,
            sequence=resource.ownership.sequence + 1,
            previous_owner_kind=resource.ownership.current_owner_kind,
            previous_owner_membership_id=resource.ownership.current_owner_membership_id,
            previous_owner_user_id=resource.ownership.current_owner_user_id,
            current_owner_kind=resource.ownership.current_owner_kind,
            current_owner_membership_id=resource.ownership.current_owner_membership_id,
            current_owner_user_id=resource.ownership.current_owner_user_id,
            visibility_policy=visibility_policy.value,
            authority_generation=generation,
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            reason_code="resource_visibility_changed",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add_all(
            (
                transition,
                _request_identity(
                    actor_user_id=principal.user_id,
                    workspace_id=workspace_id,
                    operation="resource.visibility.change",
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    result_kind="collaboration_resource",
                    result_id=resource_id,
                    trace_id=trace_id,
                    now=now,
                ),
            )
        )
        await self._fence(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            previous_generation=generation - 1,
            generation=generation,
            reason_code="resource_visibility_changed",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            resource_id=resource_id,
            resource_kind=resource_kind,
            scope_kind="resource_visibility",
        )
        await self._event(
            event_type="resource.visibility.changed",
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_id=resource_id,
            related_id=None,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            generation=generation,
            payload={
                "resourceKind": resource_kind.value,
                "visibilityPolicy": visibility_policy.value,
            },
            source=f"resource:{resource_kind.value}:{resource_id}:ownership:{transition.sequence}",
            canvas_id=resource.resource.canvas_id,
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.resource_visibility",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=resource_id,
                object_type=resource_kind.value,
                operation="resource_visibility_change",
                metadata={
                    "visibilityPolicy": visibility_policy.value,
                    "authorityGeneration": generation,
                },
            )
        )
        return ResourceRecord(resource.resource, transition)

    async def evaluate_access(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind | str,
        resource_id: uuid.UUID,
        access_level: ShareAccessLevel | str = ShareAccessLevel.VIEW,
        expected_authority_generation: int | None = None,
    ) -> ResourceAccessDecision:
        try:
            kind = ShareResourceKind(resource_kind)
            level = ShareAccessLevel(access_level)
        except ValueError:
            return self._deny_access(CollaborationPermission.RESOURCE_VIEW, "unknown_resource")
        permission = _permission_for_level(kind, level)
        decision = await self.authorization.evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=permission,
            expected_authority_generation=expected_authority_generation,
        )
        if not decision.allowed or decision.membership_id is None or decision.role is None:
            return ResourceAccessDecision(
                False,
                decision.reason_code,
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                None,
                None,
            )
        resource = await self.resources.get(
            workspace_id=workspace_id,
            resource_kind=kind,
            resource_id=resource_id,
        )
        if resource is None:
            return ResourceAccessDecision(
                False,
                "resource_not_found",
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                None,
                None,
            )
        ownership = resource.ownership
        if (
            ownership.current_owner_kind == "membership"
            and ownership.current_owner_membership_id == decision.membership_id
        ) or (
            ownership.current_owner_kind == "workspace" and decision.role is CollaborationRole.OWNER
        ):
            return ResourceAccessDecision(
                True,
                "resource_owner",
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                resource,
                None,
            )
        direct = await self._effective_share(
            workspace_id=workspace_id,
            resource_kind=kind,
            resource_id=resource_id,
            membership_id=decision.membership_id,
            now=_aware(self._now_factory()),
        )
        if (
            direct is not None
            and _ACCESS_ORDER[ShareAccessLevel(direct.transition.access_level)]
            >= (_ACCESS_ORDER[level])
        ):
            return ResourceAccessDecision(
                True,
                "direct_share",
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                resource,
                direct,
            )
        policy = ResourceVisibilityPolicy(ownership.visibility_policy)
        if policy is ResourceVisibilityPolicy.WORKSPACE_VISIBLE:
            return ResourceAccessDecision(
                True,
                "workspace_visible",
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                resource,
                None,
            )
        if policy is ResourceVisibilityPolicy.PRIVATE or kind is ShareResourceKind.CANVAS:
            return ResourceAccessDecision(
                False,
                "resource_private",
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                resource,
                None,
            )
        if resource.resource.canvas_id is None:
            return ResourceAccessDecision(
                False,
                "inheritance_parent_missing",
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                resource,
                None,
            )
        parent_level = (
            ShareAccessLevel.VIEW if level is ShareAccessLevel.VIEW else ShareAccessLevel.CONTRIBUTE
        )
        parent = await self.evaluate_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=ShareResourceKind.CANVAS,
            resource_id=resource.resource.canvas_id,
            access_level=parent_level,
            expected_authority_generation=expected_authority_generation,
        )
        if not parent.allowed:
            return ResourceAccessDecision(
                False,
                "inherited_access_denied",
                permission,
                decision.membership_id,
                decision.role,
                decision.authority_generation,
                resource,
                None,
            )
        return ResourceAccessDecision(
            True,
            "inherited_canvas_access",
            permission,
            decision.membership_id,
            decision.role,
            decision.authority_generation,
            resource,
            parent.share,
            resource.resource.canvas_id,
        )

    async def _effective_share(
        self,
        *,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind,
        resource_id: uuid.UUID,
        membership_id: uuid.UUID,
        now: datetime,
    ) -> ShareRecord | None:
        rows = (
            await self.session.scalars(
                select(CollaborationResourceShare).where(
                    CollaborationResourceShare.workspace_id == workspace_id,
                    CollaborationResourceShare.resource_kind == resource_kind.value,
                    CollaborationResourceShare.resource_id == resource_id,
                    (
                        (
                            CollaborationResourceShare.audience_kind
                            == ShareAudienceKind.WORKSPACE.value
                        )
                        | (CollaborationResourceShare.audience_membership_id == membership_id)
                    ),
                )
            )
        ).all()
        best: ShareRecord | None = None
        for share in rows:
            transition = await self._current_share(share.share_id, workspace_id)
            if (
                transition is None
                or transition.current_state != "active"
                or (transition.expires_at is not None and _aware(transition.expires_at) <= now)
            ):
                continue
            record = ShareRecord(share, transition)
            if (
                best is None
                or _ACCESS_ORDER[ShareAccessLevel(record.transition.access_level)]
                > _ACCESS_ORDER[ShareAccessLevel(best.transition.access_level)]
            ):
                best = record
        return best

    async def _current_share(
        self, share_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> CollaborationResourceShareTransition | None:
        return cast(
            CollaborationResourceShareTransition | None,
            await self.session.scalar(
                select(CollaborationResourceShareTransition)
                .where(
                    CollaborationResourceShareTransition.share_id == share_id,
                    CollaborationResourceShareTransition.workspace_id == workspace_id,
                )
                .order_by(CollaborationResourceShareTransition.sequence.desc())
                .limit(1)
            ),
        )

    @staticmethod
    def _can_manage_resource(
        resource: ResourceRecord,
        membership_id: uuid.UUID,
        role: CollaborationRole,
    ) -> bool:
        ownership = resource.ownership
        if (
            ownership.current_owner_kind == "membership"
            and ownership.current_owner_membership_id == membership_id
        ):
            return True
        return ownership.current_owner_kind == "workspace" and role in {
            CollaborationRole.OWNER,
            CollaborationRole.ADMINISTRATOR,
        }

    async def _fence(
        self,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_membership_id: uuid.UUID,
        previous_generation: int,
        generation: int,
        reason_code: str,
        trace_id: uuid.UUID,
        audit_event_id: uuid.UUID,
        scope_kind: str = "workspace",
        membership_id: uuid.UUID | None = None,
        membership_user_id: uuid.UUID | None = None,
        share_id: uuid.UUID | None = None,
        resource_id: uuid.UUID | None = None,
        resource_kind: ShareResourceKind | None = None,
    ) -> None:
        self.session.add(
            CollaborationRevocationFence(
                fence_id=uuid.uuid4(),
                workspace_id=workspace_id,
                scope_kind=scope_kind,
                membership_id=membership_id,
                membership_user_id=membership_user_id,
                share_id=share_id,
                resource_id=resource_id,
                resource_kind=resource_kind.value if resource_kind else None,
                previous_authority_generation=previous_generation,
                authority_generation=generation,
                reason_code=reason_code,
                actor_user_id=actor_user_id,
                actor_membership_id=actor_membership_id,
                trace_id=trace_id,
                audit_event_id=audit_event_id,
                recorded_at=_aware(self._now_factory()),
            )
        )
        await self.session.flush()

    async def _event(
        self,
        *,
        event_type: str,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        subject_id: uuid.UUID,
        related_id: uuid.UUID | None,
        trace_id: uuid.UUID,
        audit_event_id: uuid.UUID,
        generation: int,
        payload: dict[str, JsonValue],
        source: str,
        canvas_id: uuid.UUID | None,
    ) -> None:
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise CollaborationNotFoundError()
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=workspace.owner_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                subject_id=subject_id,
                actor_user_id=actor_user_id,
                source_identity=source,
                trace_id=trace_id,
                audit_event_id=audit_event_id,
                related_id=related_id,
                payload={**payload, "authorityGeneration": generation},
                origin_type="authenticated_user",
            )
        )

    @staticmethod
    def _deny_access(
        permission: CollaborationPermission, reason_code: str
    ) -> ResourceAccessDecision:
        return ResourceAccessDecision(False, reason_code, permission, None, None, None, None, None)


class OwnershipTransferService:
    """Accepted workspace/resource ownership transfer with one-owner invariants."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.resources = ResourceRegistryService(session)
        self.sharing = SharingService(session, now_factory=self._now_factory)
        self.memberships = MembershipService(session, now_factory=self._now_factory)
        self.authorization = CollaborationAuthorizationService(session)
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def request(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        transfer_kind: OwnershipTransferKind,
        recipient_membership_id: uuid.UUID,
        idempotency_key: str,
        resource_kind: ShareResourceKind | None = None,
        resource_id: uuid.UUID | None = None,
        expires_in_hours: int = TRANSFER_DEFAULT_HOURS,
        former_owner_role: str = CollaborationRole.ADMINISTRATOR.value,
    ) -> TransferRecord:
        _validate_idempotency_key(idempotency_key)
        if not 1 <= expires_in_hours <= TRANSFER_MAX_DAYS * 24:
            raise CollaborationValidationError()
        try:
            former_role = CollaborationRole(former_owner_role)
        except ValueError as exc:
            raise CollaborationValidationError() from exc
        if former_role is CollaborationRole.OWNER:
            raise CollaborationValidationError()
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=CollaborationAction.OWNERSHIP_TRANSFER_REQUEST,
        )
        if not decision.allowed or decision.membership_id is None or decision.role is None:
            raise CollaborationNotFoundError()
        recipient = await self.memberships.get(
            membership_id=recipient_membership_id,
            workspace_id=workspace_id,
        )
        if (
            recipient is None
            or recipient.transition.current_state != "active"
            or recipient.membership.user_id == principal.user_id
            or CollaborationPermission.OWNERSHIP_TRANSFER_ACCEPT
            not in ROLE_PERMISSION_CEILINGS[CollaborationRole(recipient.transition.current_role)]
        ):
            raise CollaborationNotFoundError()
        resource: ResourceRecord | None = None
        if transfer_kind is OwnershipTransferKind.WORKSPACE:
            if resource_kind is not None or resource_id is not None:
                raise CollaborationValidationError()
        else:
            if resource_kind is None or resource_id is None:
                raise CollaborationValidationError()
            permission_decision = await self.authorization.evaluate_permission(
                principal=principal,
                workspace_id=workspace_id,
                permission=_SHARE_PERMISSION[resource_kind],
                action=CollaborationAction.OWNERSHIP_TRANSFER_REQUEST,
            )
            resource = await self.resources.get(
                workspace_id=workspace_id,
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
            if (
                not permission_decision.allowed
                or resource is None
                or not self.sharing._can_manage_resource(
                    resource, decision.membership_id, decision.role
                )
            ):
                raise CollaborationNotFoundError()
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "transferKind": transfer_kind.value,
                "resourceKind": resource_kind.value if resource_kind else None,
                "resourceId": str(resource_id) if resource_id else None,
                "recipientMembershipId": str(recipient_membership_id),
                "expiresInHours": expires_in_hours,
                "formerOwnerRole": former_role.value,
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="ownership_transfer.request",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            record = await self.get(replay.result_id, workspace_id)
            if record is None:
                raise CollaborationConflictError()
            return TransferRecord(record.transfer, record.transition, duplicate=True)
        if await self._pending_exists(
            workspace_id=workspace_id,
            transfer_kind=transfer_kind,
            resource_kind=resource_kind,
            resource_id=resource_id,
        ):
            raise CollaborationConflictError()
        now = _aware(self._now_factory())
        transfer_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.ownership_transfer",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=transfer_id,
                object_type="ownership_transfer",
                operation="ownership_transfer_request",
                metadata={"transferKind": transfer_kind.value},
            )
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="ownership_transfer",
            subject_id=transfer_id,
            action="ownership_transfer.request",
            reason_code="ownership_transfer_requested",
            trace_id=trace_id,
            metadata={
                "transferKind": transfer_kind.value,
                "resourceKind": resource_kind.value if resource_kind else None,
                "resourceId": str(resource_id) if resource_id else None,
                "recipientMembershipId": str(recipient_membership_id),
            },
            now=now,
        )
        transfer = CollaborationOwnershipTransfer(
            transfer_id=transfer_id,
            workspace_id=workspace_id,
            transfer_kind=transfer_kind.value,
            resource_id=resource_id,
            resource_kind=resource_kind.value if resource_kind else None,
            requester_membership_id=decision.membership_id,
            requester_user_id=principal.user_id,
            recipient_membership_id=recipient.membership.membership_id,
            recipient_user_id=recipient.membership.user_id,
            former_owner_role=former_role.value,
            expires_at=now + timedelta(hours=expires_in_hours),
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            creation_trace_id=trace_id,
            creation_audit_event_id=audit.audit_event_id,
            created_at=now,
        )
        transition = CollaborationOwnershipTransferTransition(
            transition_id=uuid.uuid4(),
            transfer_id=transfer_id,
            workspace_id=workspace_id,
            sequence=0,
            previous_state=None,
            current_state=OwnershipTransferState.PENDING.value,
            authority_generation=cast(int, decision.authority_generation),
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            reason_code="ownership_transfer_requested",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add(audit)
        await self.session.flush()
        self.session.add(transfer)
        await self.session.flush()
        self.session.add_all(
            (
                transition,
                _request_identity(
                    actor_user_id=principal.user_id,
                    workspace_id=workspace_id,
                    operation="ownership_transfer.request",
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    result_kind="ownership_transfer",
                    result_id=transfer_id,
                    trace_id=trace_id,
                    now=now,
                ),
            )
        )
        await self._event(
            event_type="ownership_transfer.requested",
            transfer=transfer,
            actor_user_id=principal.user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            generation=cast(int, decision.authority_generation),
            state=OwnershipTransferState.PENDING,
            resource=resource,
            source="requested",
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.ownership_transfer",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=transfer_id,
                object_type="ownership_transfer",
                operation="ownership_transfer_request",
                metadata={"state": OwnershipTransferState.PENDING.value},
            )
        )
        return TransferRecord(transfer, transition)

    async def accept(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        transfer_id: uuid.UUID,
        idempotency_key: str,
    ) -> TransferRecord:
        return await self._decide(
            principal=principal,
            workspace_id=workspace_id,
            transfer_id=transfer_id,
            idempotency_key=idempotency_key,
            target_state=OwnershipTransferState.ACCEPTED,
        )

    async def cancel(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        transfer_id: uuid.UUID,
        idempotency_key: str,
    ) -> TransferRecord:
        return await self._decide(
            principal=principal,
            workspace_id=workspace_id,
            transfer_id=transfer_id,
            idempotency_key=idempotency_key,
            target_state=OwnershipTransferState.CANCELED,
        )

    async def reject(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        transfer_id: uuid.UUID,
        idempotency_key: str,
    ) -> TransferRecord:
        return await self._decide(
            principal=principal,
            workspace_id=workspace_id,
            transfer_id=transfer_id,
            idempotency_key=idempotency_key,
            target_state=OwnershipTransferState.REJECTED,
        )

    async def get(self, transfer_id: uuid.UUID, workspace_id: uuid.UUID) -> TransferRecord | None:
        transfer = await self.session.scalar(
            select(CollaborationOwnershipTransfer).where(
                CollaborationOwnershipTransfer.transfer_id == transfer_id,
                CollaborationOwnershipTransfer.workspace_id == workspace_id,
            )
        )
        if transfer is None:
            return None
        transition = await self.session.scalar(
            select(CollaborationOwnershipTransferTransition)
            .where(
                CollaborationOwnershipTransferTransition.transfer_id == transfer_id,
                CollaborationOwnershipTransferTransition.workspace_id == workspace_id,
            )
            .order_by(CollaborationOwnershipTransferTransition.sequence.desc())
            .limit(1)
        )
        return TransferRecord(transfer, transition) if transition is not None else None

    async def _decide(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        transfer_id: uuid.UUID,
        idempotency_key: str,
        target_state: OwnershipTransferState,
    ) -> TransferRecord:
        _validate_idempotency_key(idempotency_key)
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "transferId": str(transfer_id),
                "state": target_state.value,
            }
        )
        operation = {
            OwnershipTransferState.ACCEPTED: "ownership_transfer.accept",
            OwnershipTransferState.REJECTED: "ownership_transfer.reject",
            OwnershipTransferState.CANCELED: "ownership_transfer.cancel",
        }[target_state]
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            record = await self.get(transfer_id, workspace_id)
            if record is None:
                raise CollaborationConflictError()
            return TransferRecord(record.transfer, record.transition, duplicate=True)
        record = await self.get(transfer_id, workspace_id)
        if (
            record is None
            or record.transition.current_state != OwnershipTransferState.PENDING.value
        ):
            raise CollaborationNotFoundError()
        transfer = record.transfer
        now = _aware(self._now_factory())
        if _aware(transfer.expires_at) <= now:
            raise CollaborationNotFoundError()
        actor = await self.memberships.resolve(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            require_active=True,
        )
        if actor is None:
            raise CollaborationNotFoundError()
        if target_state in {OwnershipTransferState.ACCEPTED, OwnershipTransferState.REJECTED}:
            if (
                actor.membership.membership_id != transfer.recipient_membership_id
                or principal.user_id != transfer.recipient_user_id
            ):
                raise CollaborationNotFoundError()
        elif (
            actor.membership.membership_id != transfer.requester_membership_id
            or principal.user_id != transfer.requester_user_id
        ):
            raise CollaborationNotFoundError()
        recipient = await self.memberships.get(
            membership_id=transfer.recipient_membership_id,
            workspace_id=workspace_id,
        )
        if recipient is None or recipient.transition.current_state != "active":
            raise CollaborationNotFoundError()
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.ownership_transfer",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=transfer_id,
                object_type="ownership_transfer",
                operation=f"ownership_transfer_{target_state.value}",
                metadata={"transferKind": transfer.transfer_kind},
            )
        )
        authority = await self.session.get(WorkspaceAuthorityVersion, workspace_id)
        if authority is None:
            raise CollaborationNotFoundError()
        generation = authority.authority_generation
        if target_state is OwnershipTransferState.ACCEPTED:
            generation = await _increment_authority(
                self.session,
                workspace_id=workspace_id,
                trace_id=trace_id,
                now=now,
            )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="ownership_transfer",
            subject_id=transfer_id,
            action=operation,
            reason_code=f"ownership_transfer_{target_state.value}",
            trace_id=trace_id,
            metadata={
                "transferKind": transfer.transfer_kind,
                "resourceKind": transfer.resource_kind,
                "resourceId": str(transfer.resource_id) if transfer.resource_id else None,
                "state": target_state.value,
            },
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        resource: ResourceRecord | None = None
        if target_state is OwnershipTransferState.ACCEPTED:
            if transfer.transfer_kind == OwnershipTransferKind.WORKSPACE.value:
                await self._accept_workspace(transfer, recipient, generation, trace_id, audit, now)
            else:
                resource = await self._accept_resource(
                    transfer, recipient, generation, trace_id, audit, now
                )
        transition = CollaborationOwnershipTransferTransition(
            transition_id=uuid.uuid4(),
            transfer_id=transfer_id,
            workspace_id=workspace_id,
            sequence=record.transition.sequence + 1,
            previous_state=OwnershipTransferState.PENDING.value,
            current_state=target_state.value,
            authority_generation=generation,
            actor_user_id=principal.user_id,
            actor_membership_id=actor.membership.membership_id,
            reason_code=f"ownership_transfer_{target_state.value}",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add_all(
            (
                transition,
                _request_identity(
                    actor_user_id=principal.user_id,
                    workspace_id=workspace_id,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    result_kind="ownership_transfer",
                    result_id=transfer_id,
                    trace_id=trace_id,
                    now=now,
                ),
            )
        )
        if target_state is OwnershipTransferState.ACCEPTED:
            await self.sharing._fence(
                workspace_id=workspace_id,
                actor_user_id=principal.user_id,
                actor_membership_id=actor.membership.membership_id,
                previous_generation=generation - 1,
                generation=generation,
                reason_code="ownership_transfer_accepted",
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                resource_id=transfer.resource_id,
                resource_kind=(
                    ShareResourceKind(transfer.resource_kind) if transfer.resource_kind else None
                ),
                scope_kind=(
                    "resource_ownership"
                    if transfer.transfer_kind == OwnershipTransferKind.RESOURCE.value
                    else "workspace"
                ),
            )
        await self._event(
            event_type=f"ownership_transfer.{target_state.value}",
            transfer=transfer,
            actor_user_id=principal.user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            generation=generation,
            state=target_state,
            resource=resource,
            source=f"transition:{transition.sequence}",
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.ownership_transfer",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=transfer_id,
                object_type="ownership_transfer",
                operation=f"ownership_transfer_{target_state.value}",
                metadata={"state": target_state.value, "authorityGeneration": generation},
            )
        )
        return TransferRecord(transfer, transition)

    async def _accept_workspace(
        self,
        transfer: CollaborationOwnershipTransfer,
        recipient: MembershipView,
        generation: int,
        trace_id: uuid.UUID,
        audit: CollaborationAuditEvent,
        now: datetime,
    ) -> None:
        workspace = await self.session.get(Workspace, transfer.workspace_id)
        requester = await self.memberships.get(
            membership_id=transfer.requester_membership_id,
            workspace_id=transfer.workspace_id,
        )
        if (
            workspace is None
            or workspace.owner_id != transfer.requester_user_id
            or requester is None
            or requester.transition.current_state != "active"
            or requester.transition.current_role != CollaborationRole.OWNER.value
        ):
            raise CollaborationNotFoundError()
        workspace.owner_id = transfer.recipient_user_id
        workspace.version += 1
        former = WorkspaceMembershipTransition(
            transition_id=uuid.uuid4(),
            membership_id=requester.membership.membership_id,
            user_id=requester.membership.user_id,
            workspace_id=transfer.workspace_id,
            sequence=requester.transition.sequence + 1,
            previous_state="active",
            current_state="active",
            previous_role=CollaborationRole.OWNER.value,
            current_role=transfer.former_owner_role,
            reason_code="workspace_ownership_transferred",
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            authority_generation=generation,
            actor_user_id=transfer.recipient_user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add(former)
        await self.session.flush()
        new_owner = WorkspaceMembershipTransition(
            transition_id=uuid.uuid4(),
            membership_id=recipient.membership.membership_id,
            user_id=recipient.membership.user_id,
            workspace_id=transfer.workspace_id,
            sequence=recipient.transition.sequence + 1,
            previous_state="active",
            current_state="active",
            previous_role=recipient.transition.current_role,
            current_role=CollaborationRole.OWNER.value,
            reason_code="workspace_ownership_transferred",
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            authority_generation=generation,
            actor_user_id=transfer.recipient_user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add(new_owner)
        await self.session.flush()

    async def _accept_resource(
        self,
        transfer: CollaborationOwnershipTransfer,
        recipient: MembershipView,
        generation: int,
        trace_id: uuid.UUID,
        audit: CollaborationAuditEvent,
        now: datetime,
    ) -> ResourceRecord:
        if transfer.resource_id is None or transfer.resource_kind is None:
            raise CollaborationConflictError()
        resource = await self.resources.get(
            workspace_id=transfer.workspace_id,
            resource_kind=transfer.resource_kind,
            resource_id=transfer.resource_id,
        )
        if resource is None:
            raise CollaborationNotFoundError()
        ownership = resource.ownership
        if ownership.current_owner_kind == "membership" and (
            ownership.current_owner_membership_id != transfer.requester_membership_id
        ):
            raise CollaborationNotFoundError()
        transition = CollaborationResourceOwnershipTransition(
            transition_id=uuid.uuid4(),
            resource_id=transfer.resource_id,
            workspace_id=transfer.workspace_id,
            resource_kind=transfer.resource_kind,
            sequence=ownership.sequence + 1,
            previous_owner_kind=ownership.current_owner_kind,
            previous_owner_membership_id=ownership.current_owner_membership_id,
            previous_owner_user_id=ownership.current_owner_user_id,
            current_owner_kind="membership",
            current_owner_membership_id=recipient.membership.membership_id,
            current_owner_user_id=recipient.membership.user_id,
            visibility_policy=ownership.visibility_policy,
            authority_generation=generation,
            actor_user_id=recipient.membership.user_id,
            actor_membership_id=recipient.membership.membership_id,
            reason_code="resource_ownership_transferred",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add(transition)
        await self.session.flush()
        await self.sharing._event(
            event_type="resource.ownership_changed",
            workspace_id=transfer.workspace_id,
            actor_user_id=recipient.membership.user_id,
            subject_id=transfer.resource_id,
            related_id=transfer.transfer_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            generation=generation,
            payload={
                "resourceKind": transfer.resource_kind,
                "ownerKind": "membership",
            },
            source=f"resource:{transfer.resource_kind}:{transfer.resource_id}:"
            f"ownership:{transition.sequence}",
            canvas_id=resource.resource.canvas_id,
        )
        return ResourceRecord(resource.resource, transition)

    async def _pending_exists(
        self,
        *,
        workspace_id: uuid.UUID,
        transfer_kind: OwnershipTransferKind,
        resource_kind: ShareResourceKind | None,
        resource_id: uuid.UUID | None,
    ) -> bool:
        rows = (
            await self.session.scalars(
                select(CollaborationOwnershipTransfer).where(
                    CollaborationOwnershipTransfer.workspace_id == workspace_id,
                    CollaborationOwnershipTransfer.transfer_kind == transfer_kind.value,
                    CollaborationOwnershipTransfer.resource_kind
                    == (resource_kind.value if resource_kind else None),
                    CollaborationOwnershipTransfer.resource_id == resource_id,
                )
            )
        ).all()
        now = _aware(self._now_factory())
        for transfer in rows:
            record = await self.get(transfer.transfer_id, workspace_id)
            if (
                record is not None
                and record.transition.current_state == OwnershipTransferState.PENDING.value
                and _aware(transfer.expires_at) > now
            ):
                return True
        return False

    async def _event(
        self,
        *,
        event_type: str,
        transfer: CollaborationOwnershipTransfer,
        actor_user_id: uuid.UUID,
        trace_id: uuid.UUID,
        audit_event_id: uuid.UUID,
        generation: int,
        state: OwnershipTransferState,
        resource: ResourceRecord | None,
        source: str,
    ) -> None:
        workspace = await self.session.get(Workspace, transfer.workspace_id)
        if workspace is None:
            raise CollaborationNotFoundError()
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=workspace.owner_id,
                workspace_id=transfer.workspace_id,
                canvas_id=resource.resource.canvas_id if resource else None,
                subject_id=transfer.transfer_id,
                actor_user_id=actor_user_id,
                source_identity=f"ownership-transfer:{transfer.transfer_id}:{source}",
                trace_id=trace_id,
                audit_event_id=audit_event_id,
                related_id=transfer.resource_id,
                payload={
                    "transferKind": transfer.transfer_kind,
                    "resourceKind": transfer.resource_kind,
                    "state": state.value,
                    "authorityGeneration": generation,
                },
                origin_type="authenticated_user",
            )
        )


class RevocationFenceService:
    """Capture bounded authority and reject every stale later boundary."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.authorization = CollaborationAuthorizationService(session)

    async def capture(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        permission: CollaborationPermission,
        boundary: AuthorityBoundary,
        trace_id: uuid.UUID,
        resource: ResourceRecord | None = None,
        share: ShareRecord | None = None,
        controlled_execution_id: uuid.UUID | None = None,
        workflow_execution_id: uuid.UUID | None = None,
        request_identity_id: uuid.UUID | None = None,
    ) -> CollaborationAuthoritySnapshot:
        decision = await self.authorization.evaluate_permission(
            principal=principal,
            workspace_id=workspace_id,
            permission=permission,
        )
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.role is None
            or decision.authority_generation is None
        ):
            raise CollaborationNotFoundError()
        scope = {
            "userId": str(principal.user_id),
            "membershipId": str(decision.membership_id),
            "workspaceId": str(workspace_id),
            "role": decision.role.value,
            "permission": permission.value,
            "boundary": boundary.value,
            "resourceKind": resource.resource.resource_kind if resource else None,
            "resourceId": str(resource.resource.resource_id) if resource else None,
            "shareId": str(share.share.share_id) if share else None,
            "ownershipTransitionId": (str(resource.ownership.transition_id) if resource else None),
            "authorityGeneration": decision.authority_generation,
            "controlledExecutionId": (
                str(controlled_execution_id) if controlled_execution_id else None
            ),
            "workflowExecutionId": (str(workflow_execution_id) if workflow_execution_id else None),
        }
        snapshot = CollaborationAuthoritySnapshot(
            snapshot_id=uuid.uuid4(),
            user_id=principal.user_id,
            membership_id=decision.membership_id,
            workspace_id=workspace_id,
            role=decision.role.value,
            permission=permission.value,
            boundary=boundary.value,
            resource_id=resource.resource.resource_id if resource else None,
            resource_kind=resource.resource.resource_kind if resource else None,
            share_id=share.share.share_id if share else None,
            ownership_transition_id=(resource.ownership.transition_id if resource else None),
            authority_generation=decision.authority_generation,
            controlled_execution_id=controlled_execution_id,
            workflow_execution_id=workflow_execution_id,
            request_identity_id=request_identity_id,
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            scope_digest=_digest(scope),
            trace_id=trace_id,
            captured_at=_aware(self._now_factory()),
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def assert_current(
        self,
        snapshot: CollaborationAuthoritySnapshot,
        *,
        boundary: AuthorityBoundary,
    ) -> None:
        workspace = await self.session.get(Workspace, snapshot.workspace_id)
        authority = await self.session.get(WorkspaceAuthorityVersion, snapshot.workspace_id)
        if (
            workspace is None
            or workspace.deleted_at is not None
            or workspace.lifecycle_state not in {"created", "active"}
            or authority is None
            or authority.authority_generation != snapshot.authority_generation
        ):
            raise CollaborationNotFoundError()
        principal = Principal(
            user_id=snapshot.user_id,
            email="snapshot@invalid.local",
            display_name="Authority snapshot",
            session_id=uuid.uuid4(),
            csrf_token_hash="snapshot",
        )
        decision = await self.authorization.evaluate_permission(
            principal=principal,
            workspace_id=snapshot.workspace_id,
            permission=snapshot.permission,
            expected_authority_generation=snapshot.authority_generation,
        )
        if (
            not decision.allowed
            or decision.membership_id != snapshot.membership_id
            or decision.role is None
            or decision.role.value != snapshot.role
        ):
            raise CollaborationNotFoundError()
        if snapshot.resource_id is not None and snapshot.resource_kind is not None:
            resource = await ResourceRegistryService(self.session).get(
                workspace_id=snapshot.workspace_id,
                resource_kind=snapshot.resource_kind,
                resource_id=snapshot.resource_id,
            )
            if (
                resource is None
                or resource.ownership.transition_id != snapshot.ownership_transition_id
            ):
                raise CollaborationNotFoundError()
        if snapshot.share_id is not None:
            transition = await SharingService(self.session)._current_share(
                snapshot.share_id, snapshot.workspace_id
            )
            if (
                transition is None
                or transition.current_state != "active"
                or (
                    transition.expires_at is not None
                    and _aware(transition.expires_at) <= _aware(self._now_factory())
                )
            ):
                raise CollaborationNotFoundError()
        if boundary not in AuthorityBoundary:
            raise CollaborationValidationError()

    async def require_controlled_execution(
        self,
        *,
        execution_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        boundary: AuthorityBoundary,
    ) -> None:
        snapshot = await self.session.scalar(
            select(CollaborationAuthoritySnapshot)
            .where(
                CollaborationAuthoritySnapshot.controlled_execution_id == execution_id,
                CollaborationAuthoritySnapshot.user_id == user_id,
                CollaborationAuthoritySnapshot.workspace_id == workspace_id,
            )
            .order_by(CollaborationAuthoritySnapshot.captured_at.desc())
            .limit(1)
        )
        if snapshot is None:
            authority = await self.session.get(WorkspaceAuthorityVersion, workspace_id)
            if authority is None:
                return
            raise CollaborationNotFoundError()
        await self.assert_current(snapshot, boundary=boundary)

    async def require_workflow_execution(
        self,
        *,
        execution_id: uuid.UUID,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        boundary: AuthorityBoundary,
    ) -> None:
        snapshot = await self.session.scalar(
            select(CollaborationAuthoritySnapshot)
            .where(
                CollaborationAuthoritySnapshot.workflow_execution_id == execution_id,
                CollaborationAuthoritySnapshot.user_id == user_id,
                CollaborationAuthoritySnapshot.workspace_id == workspace_id,
            )
            .order_by(CollaborationAuthoritySnapshot.captured_at.desc())
            .limit(1)
        )
        if snapshot is None:
            authority = await self.session.get(WorkspaceAuthorityVersion, workspace_id)
            if authority is None:
                return
            raise CollaborationNotFoundError()
        await self.assert_current(snapshot, boundary=boundary)


def _permission_for_level(
    kind: ShareResourceKind, level: ShareAccessLevel
) -> CollaborationPermission:
    if level is ShareAccessLevel.VIEW:
        return _VIEW_PERMISSION[kind]
    if level is ShareAccessLevel.CONTRIBUTE:
        return _EDIT_PERMISSION[kind]
    return _SHARE_PERMISSION[kind]


def _audience_key(
    kind: ShareAudienceKind,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID | None,
) -> str:
    if kind is ShareAudienceKind.WORKSPACE:
        return f"workspace:{workspace_id}"
    if membership_id is None:
        raise CollaborationValidationError()
    return f"membership:{membership_id}"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "BULK_REVOCATION_MAX",
    "SHARE_BATCH_MAX",
    "SHARE_PAGE_DEFAULT",
    "SHARE_PAGE_MAX",
    "TRANSFER_DEFAULT_HOURS",
    "TRANSFER_MAX_DAYS",
    "AuthorityBoundary",
    "OwnershipTransferKind",
    "OwnershipTransferService",
    "ResourceAccessDecision",
    "ResourceRecord",
    "ResourceRegistryService",
    "ResourceVisibilityPolicy",
    "RevocationFenceService",
    "ShareAccessLevel",
    "ShareAudienceKind",
    "ShareRecord",
    "ShareResourceKind",
    "ShareTarget",
    "SharingService",
    "TransferRecord",
]
