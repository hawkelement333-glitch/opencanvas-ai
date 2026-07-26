from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    CollaborationAuthoritySnapshot,
    CollaborationResource,
    CollaborationResourceOwnershipTransition,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration import CollaborationNotFoundError
from opencanvas_api.services.collaboration_authority import CollaborationPermission
from opencanvas_api.services.collaboration_resources import (
    AuthorityBoundary,
    ResourceAccessDecision,
    RevocationFenceService,
    ShareResourceKind,
    SharingService,
)


@dataclass(frozen=True, slots=True)
class SharedResourceAuthority:
    """Exact current visibility and invocation authority for one typed identity."""

    user_id: uuid.UUID
    workspace_id: uuid.UUID
    resource_kind: ShareResourceKind
    resource_id: uuid.UUID
    access: ResourceAccessDecision

    @property
    def membership_id(self) -> uuid.UUID:
        if self.access.membership_id is None:
            raise CollaborationNotFoundError()
        return self.access.membership_id


class SharedInvocationGovernanceService:
    """Deny-by-default composition of typed visibility and invocation permission."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sharing = SharingService(session)
        self.fences = RevocationFenceService(session)

    async def require_visibility(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind,
        resource_id: uuid.UUID,
        expected_authority_generation: int | None = None,
    ) -> SharedResourceAuthority:
        principal = _principal(user_id)
        access = await self.sharing.evaluate_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            expected_authority_generation=expected_authority_generation,
        )
        if not access.allowed or access.membership_id is None:
            raise CollaborationNotFoundError()
        return SharedResourceAuthority(
            user_id=user_id,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            access=access,
        )

    async def ensure_registered_owner_resource(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        resource_kind: ShareResourceKind,
        resource_id: uuid.UUID,
        trace_id: uuid.UUID,
        created_at: datetime,
    ) -> None:
        """Mirror the 6.3 registration trigger for metadata-created test schemas."""

        if resource_kind not in {ShareResourceKind.WORKFLOW, ShareResourceKind.AGENT}:
            raise CollaborationNotFoundError()
        key = {
            "resource_id": resource_id,
            "workspace_id": workspace_id,
            "resource_kind": resource_kind.value,
        }
        if await self.session.get(CollaborationResource, key) is not None:
            return
        decision = await self.sharing.authorization.evaluate_permission(
            principal=_principal(user_id),
            workspace_id=workspace_id,
            permission=_view_permission(resource_kind),
        )
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.authority_generation is None
        ):
            raise CollaborationNotFoundError()
        resource = CollaborationResource(
            resource_id=resource_id,
            workspace_id=workspace_id,
            resource_kind=resource_kind.value,
            canvas_id=canvas_id,
            canonical_object_id=None,
            workflow_definition_id=(
                resource_id if resource_kind is ShareResourceKind.WORKFLOW else None
            ),
            agent_id=resource_id if resource_kind is ShareResourceKind.AGENT else None,
            target_user_id=user_id,
            creator_user_id=user_id,
            creation_trace_id=trace_id,
            created_at=_utc(created_at),
        )
        ownership = CollaborationResourceOwnershipTransition(
            transition_id=uuid.uuid5(
                resource_id,
                f"collaboration-resource:{resource_kind.value}:ownership:0",
            ),
            resource_id=resource_id,
            workspace_id=workspace_id,
            resource_kind=resource_kind.value,
            sequence=0,
            previous_owner_kind=None,
            previous_owner_membership_id=None,
            previous_owner_user_id=None,
            current_owner_kind="workspace",
            current_owner_membership_id=None,
            current_owner_user_id=None,
            visibility_policy="private",
            authority_generation=decision.authority_generation,
            actor_user_id=user_id,
            actor_membership_id=decision.membership_id,
            reason_code="resource_registration",
            trace_id=trace_id,
            audit_event_id=None,
            recorded_at=_utc(created_at),
        )
        self.session.add_all((resource, ownership))
        await self.session.flush()

    async def require_invocation(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind,
        resource_id: uuid.UUID,
        expected_authority_generation: int | None = None,
    ) -> SharedResourceAuthority:
        authority = await self.require_visibility(
            user_id=user_id,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            expected_authority_generation=expected_authority_generation,
        )
        permission = _invocation_permission(resource_kind)
        decision = await self.sharing.authorization.evaluate_permission(
            principal=_principal(user_id),
            workspace_id=workspace_id,
            permission=permission,
            expected_authority_generation=expected_authority_generation,
        )
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.membership_id != authority.membership_id
            or decision.authority_generation != authority.access.authority_generation
        ):
            raise CollaborationNotFoundError()
        return authority

    async def capture(
        self,
        authority: SharedResourceAuthority,
        *,
        trace_id: uuid.UUID,
        workflow_execution_id: uuid.UUID,
    ) -> CollaborationAuthoritySnapshot:
        return await self.fences.capture(
            principal=_principal(authority.user_id),
            workspace_id=authority.workspace_id,
            permission=_invocation_permission(authority.resource_kind),
            boundary=AuthorityBoundary.CLAIM,
            trace_id=trace_id,
            resource=authority.access.resource,
            share=authority.access.share,
            workflow_execution_id=workflow_execution_id,
        )


def _principal(user_id: uuid.UUID) -> Principal:
    return Principal(
        user_id=user_id,
        email="shared-governance@invalid.local",
        display_name="Shared invocation authority",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )


def _invocation_permission(resource_kind: ShareResourceKind) -> CollaborationPermission:
    if resource_kind is ShareResourceKind.WORKFLOW:
        return CollaborationPermission.WORKFLOW_INVOKE
    if resource_kind is ShareResourceKind.AGENT:
        return CollaborationPermission.AGENT_INVOKE
    raise CollaborationNotFoundError()


def _view_permission(resource_kind: ShareResourceKind) -> CollaborationPermission:
    if resource_kind is ShareResourceKind.WORKFLOW:
        return CollaborationPermission.WORKFLOW_VIEW
    if resource_kind is ShareResourceKind.AGENT:
        return CollaborationPermission.AGENT_VIEW
    raise CollaborationNotFoundError()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "SharedInvocationGovernanceService",
    "SharedResourceAuthority",
]
