from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    CollaborationApprovalAuthorityAssignment,
    CollaborationApprovalAuthorityTransition,
    CollaborationAuditEvent,
    CollaborationRequestIdentity,
    CollaborationReviewerEligibilityEvidence,
    ControlledAgentApproval,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembershipTransition,
)
from opencanvas_api.services.agents.contracts import Capability, ResourceKind, RiskClass
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
    CollaborationAction,
    CollaborationAuthorizationService,
    CollaborationRole,
)
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import CompleteTraceInput, StartTraceInput, TraceService

AssignableRole = Literal["administrator", "editor", "approver", "member", "viewer"]
MembershipTargetState = Literal["active", "suspended", "removed"]
ApprovalAuthorityState = Literal["active", "revoked", "superseded"]
MAX_ASSIGNMENT_DAYS = 30
_ADMIN_MANAGED_ROLES = frozenset(
    {
        CollaborationRole.EDITOR,
        CollaborationRole.APPROVER,
        CollaborationRole.MEMBER,
        CollaborationRole.VIEWER,
    }
)
_RISK_ORDER = {
    RiskClass.R0_OBSERVATION: 0,
    RiskClass.R1_DRAFT: 1,
    RiskClass.R2_TRANSIENT_ACTION: 2,
    RiskClass.R3_DURABLE_WRITE: 3,
}


@dataclass(frozen=True, slots=True)
class ApprovalAuthorityView:
    assignment: CollaborationApprovalAuthorityAssignment
    transition: CollaborationApprovalAuthorityTransition
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ReviewerEligibilityDecision:
    allowed: bool
    reason_code: str
    assignment_id: uuid.UUID | None
    membership_id: uuid.UUID | None
    authority_generation: int | None


class MembershipAuthorityService:
    """Atomic, append-only membership role and lifecycle administration."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.memberships = MembershipService(session, now_factory=self._now_factory)
        self.authorization = CollaborationAuthorizationService(session)
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def change_role(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        role: str,
        idempotency_key: str,
    ) -> MembershipView:
        try:
            requested_role = CollaborationRole(role)
        except ValueError as exc:
            raise CollaborationValidationError() from exc
        if requested_role is CollaborationRole.OWNER:
            raise CollaborationValidationError()
        return await self._transition(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=membership_id,
            action=CollaborationAction.MEMBERSHIP_ROLE_CHANGE,
            operation="membership.role.change",
            target_state="active",
            target_role=requested_role,
            idempotency_key=idempotency_key,
            reason_code="membership_role_changed",
            event_type="membership.role_changed",
        )

    async def suspend(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        idempotency_key: str,
    ) -> MembershipView:
        return await self._transition(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=membership_id,
            action=CollaborationAction.MEMBERSHIP_SUSPEND,
            operation="membership.suspend",
            target_state="suspended",
            target_role=None,
            idempotency_key=idempotency_key,
            reason_code="membership_suspended",
            event_type="membership.suspended",
        )

    async def restore(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        idempotency_key: str,
    ) -> MembershipView:
        return await self._transition(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=membership_id,
            action=CollaborationAction.MEMBERSHIP_RESTORE,
            operation="membership.restore",
            target_state="active",
            target_role=None,
            idempotency_key=idempotency_key,
            reason_code="membership_restored",
            event_type="membership.restored",
        )

    async def remove(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        idempotency_key: str,
    ) -> MembershipView:
        return await self._transition(
            principal=principal,
            workspace_id=workspace_id,
            membership_id=membership_id,
            action=CollaborationAction.MEMBERSHIP_REMOVE,
            operation="membership.remove",
            target_state="removed",
            target_role=None,
            idempotency_key=idempotency_key,
            reason_code="membership_removed",
            event_type="membership.removed",
        )

    async def _transition(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        action: CollaborationAction,
        operation: str,
        target_state: MembershipTargetState,
        target_role: CollaborationRole | None,
        idempotency_key: str,
        reason_code: str,
        event_type: str,
    ) -> MembershipView:
        _validate_idempotency_key(idempotency_key)
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=action,
        )
        if not decision.allowed or decision.role is None or decision.membership_id is None:
            raise CollaborationNotFoundError()
        target = await self.memberships.get(
            membership_id=membership_id,
            workspace_id=workspace_id,
        )
        workspace = await self.session.get(Workspace, workspace_id)
        if target is None or workspace is None:
            raise CollaborationNotFoundError()
        previous = target.transition
        previous_role = CollaborationRole(previous.current_role)
        if previous_role is CollaborationRole.OWNER or membership_id == decision.membership_id:
            raise CollaborationNotFoundError()
        if decision.role is CollaborationRole.ADMINISTRATOR:
            if previous_role not in _ADMIN_MANAGED_ROLES:
                raise CollaborationNotFoundError()
            if target_role is not None and target_role not in _ADMIN_MANAGED_ROLES:
                raise CollaborationNotFoundError()
        resolved_role = target_role or previous_role
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "membershipId": str(membership_id),
                "state": target_state,
                "role": resolved_role.value,
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            replayed = await self.memberships.get(
                membership_id=replay.result_id,
                workspace_id=workspace_id,
            )
            if replayed is None:
                raise CollaborationConflictError()
            return replayed
        if target_role is not None and previous.current_state != "active":
            raise CollaborationConflictError()
        if target_state == "suspended" and previous.current_state != "active":
            raise CollaborationConflictError()
        if (
            target_state == "active"
            and target_role is None
            and previous.current_state != "suspended"
        ):
            raise CollaborationConflictError()
        if target_state == "removed" and previous.current_state not in {"active", "suspended"}:
            raise CollaborationConflictError()
        if target_state == previous.current_state and resolved_role is previous_role:
            raise CollaborationConflictError()

        now = _aware_utc(self._now_factory())
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.membership",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=membership_id,
                object_type="workspace_membership",
                operation=operation.replace(".", "_"),
                metadata={"targetState": target_state, "targetRole": resolved_role.value},
            )
        )
        generation = await _increment_authority(
            self.session, workspace_id=workspace_id, trace_id=trace_id, now=now
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="workspace_membership",
            subject_id=membership_id,
            action=operation,
            reason_code=reason_code,
            trace_id=trace_id,
            metadata={
                "previousState": previous.current_state,
                "state": target_state,
                "previousRole": previous.current_role,
                "role": resolved_role.value,
            },
            now=now,
        )
        transition = WorkspaceMembershipTransition(
            transition_id=uuid.uuid4(),
            membership_id=target.membership.membership_id,
            user_id=target.membership.user_id,
            workspace_id=workspace_id,
            sequence=previous.sequence + 1,
            previous_state=previous.current_state,
            current_state=target_state,
            previous_role=previous.current_role,
            current_role=resolved_role.value,
            reason_code=reason_code,
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            authority_generation=generation,
            actor_user_id=principal.user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        request = _request_identity(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_kind="workspace_membership",
            result_id=membership_id,
            trace_id=trace_id,
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        self.session.add_all((transition, request))
        await self.session.flush()
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=workspace.owner_id,
                workspace_id=workspace_id,
                canvas_id=None,
                subject_id=membership_id,
                actor_user_id=principal.user_id,
                source_identity=f"membership:{membership_id}:transition:{transition.sequence}",
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                payload={
                    "state": target_state,
                    "role": resolved_role.value,
                    "previousState": previous.current_state,
                    "previousRole": previous.current_role,
                    "reasonCode": reason_code,
                    "authorityGeneration": generation,
                },
                origin_type="authenticated_user",
            )
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.membership",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=membership_id,
                object_type="workspace_membership",
                operation=operation.replace(".", "_"),
                metadata={"state": target_state, "role": resolved_role.value},
            )
        )
        return MembershipView(target.membership, transition)


class ApprovalAuthorityService:
    """Bounded reviewer assignments; never a Milestone 4 approval or grant."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.authorization = CollaborationAuthorizationService(session)
        self.memberships = MembershipService(session, now_factory=self._now_factory)
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def assign(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        capability: str,
        resource_kind: str,
        resource_id: uuid.UUID,
        maximum_risk_class: str,
        expires_in_days: int,
        idempotency_key: str,
        supersedes_assignment_id: uuid.UUID | None = None,
    ) -> ApprovalAuthorityView:
        action = (
            CollaborationAction.APPROVAL_AUTHORITY_REPLACE
            if supersedes_assignment_id is not None
            else CollaborationAction.APPROVAL_AUTHORITY_ASSIGN
        )
        operation = (
            "approval_authority.replace"
            if supersedes_assignment_id is not None
            else "approval_authority.assign"
        )
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=action,
        )
        if not decision.allowed or decision.membership_id is None:
            raise CollaborationNotFoundError()
        target = await self.memberships.get(membership_id=membership_id, workspace_id=workspace_id)
        if (
            target is None
            or target.transition.current_state != "active"
            or target.membership.user_id == principal.user_id
            or target.transition.current_role not in {"approver", "administrator"}
        ):
            raise CollaborationNotFoundError()
        try:
            closed_capability = Capability(capability)
            closed_resource_kind = ResourceKind(resource_kind)
            closed_risk = RiskClass(maximum_risk_class)
        except ValueError as exc:
            raise CollaborationValidationError() from exc
        if (
            closed_risk is RiskClass.R4_PROHIBITED
            or not 1 <= expires_in_days <= MAX_ASSIGNMENT_DAYS
        ):
            raise CollaborationValidationError()
        _validate_idempotency_key(idempotency_key)
        previous: ApprovalAuthorityView | None = None
        if supersedes_assignment_id is not None:
            previous = await self.get(
                assignment_id=supersedes_assignment_id,
                workspace_id=workspace_id,
            )
            if previous is None or previous.transition.current_state != "active":
                raise CollaborationNotFoundError()
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "membershipId": str(membership_id),
                "capability": closed_capability.value,
                "resourceKind": closed_resource_kind.value,
                "resourceId": str(resource_id),
                "maximumRiskClass": closed_risk.value,
                "expiresInDays": expires_in_days,
                "supersedesAssignmentId": (
                    str(supersedes_assignment_id) if supersedes_assignment_id else None
                ),
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            view = await self.get(assignment_id=replay.result_id, workspace_id=workspace_id)
            if view is None:
                raise CollaborationConflictError()
            return ApprovalAuthorityView(view.assignment, view.transition, duplicate=True)

        now = _aware_utc(self._now_factory())
        assignment_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.approval_authority",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=assignment_id,
                object_type="approval_authority_assignment",
                operation=operation.replace(".", "_"),
                metadata={
                    "capability": closed_capability.value,
                    "resourceKind": closed_resource_kind.value,
                    "maximumRiskClass": closed_risk.value,
                },
            )
        )
        generation = await _increment_authority(
            self.session, workspace_id=workspace_id, trace_id=trace_id, now=now
        )
        scope: dict[str, object] = {
            "workspaceId": str(workspace_id),
            "membershipId": str(membership_id),
            "reviewerUserId": str(target.membership.user_id),
            "capability": closed_capability.value,
            "resourceKind": closed_resource_kind.value,
            "resourceId": str(resource_id),
            "maximumRiskClass": closed_risk.value,
            "policyVersion": COLLABORATION_POLICY_VERSION,
        }
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="approval_authority_assignment",
            subject_id=assignment_id,
            action=operation,
            reason_code="approval_authority_assigned",
            trace_id=trace_id,
            metadata=scope,
            now=now,
        )
        assignment = CollaborationApprovalAuthorityAssignment(
            assignment_id=assignment_id,
            workspace_id=workspace_id,
            membership_id=membership_id,
            reviewer_user_id=target.membership.user_id,
            issuer_membership_id=decision.membership_id,
            issuer_user_id=principal.user_id,
            capability=closed_capability.value,
            resource_kind=closed_resource_kind.value,
            resource_id=resource_id,
            maximum_risk_class=closed_risk.value,
            valid_from=now,
            expires_at=now + timedelta(days=expires_in_days),
            conflict_policy="deny_self_review",
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            scope_digest=_digest(scope),
            supersedes_assignment_id=supersedes_assignment_id,
            creation_trace_id=trace_id,
            creation_audit_event_id=audit.audit_event_id,
            created_at=now,
        )
        transition = CollaborationApprovalAuthorityTransition(
            transition_id=uuid.uuid4(),
            assignment_id=assignment_id,
            membership_id=membership_id,
            reviewer_user_id=target.membership.user_id,
            workspace_id=workspace_id,
            sequence=0,
            previous_state=None,
            current_state="active",
            reason_code="approval_authority_assigned",
            authority_generation=generation,
            actor_user_id=principal.user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        request = _request_identity(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_kind="approval_authority_assignment",
            result_id=assignment_id,
            trace_id=trace_id,
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        self.session.add(assignment)
        await self.session.flush()
        self.session.add_all((transition, request))
        if previous is not None:
            self.session.add(
                CollaborationApprovalAuthorityTransition(
                    transition_id=uuid.uuid4(),
                    assignment_id=previous.assignment.assignment_id,
                    membership_id=previous.assignment.membership_id,
                    reviewer_user_id=previous.assignment.reviewer_user_id,
                    workspace_id=workspace_id,
                    sequence=previous.transition.sequence + 1,
                    previous_state="active",
                    current_state="superseded",
                    reason_code="approval_authority_replaced",
                    authority_generation=generation,
                    actor_user_id=principal.user_id,
                    trace_id=trace_id,
                    audit_event_id=audit.audit_event_id,
                    recorded_at=now,
                )
            )
        await self.session.flush()
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise CollaborationNotFoundError()
        await self.events.record(
            CreateDomainEvent(
                event_type=(
                    "approval_authority.replaced"
                    if supersedes_assignment_id
                    else "approval_authority.assigned"
                ),
                user_id=workspace.owner_id,
                workspace_id=workspace_id,
                canvas_id=None,
                subject_id=assignment_id,
                actor_user_id=principal.user_id,
                source_identity=f"approval-authority:{assignment_id}:active",
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                related_id=membership_id,
                payload={
                    "state": "active",
                    "reasonCode": "approval_authority_assigned",
                    "authorityGeneration": generation,
                    "capability": closed_capability.value,
                    "resourceKind": closed_resource_kind.value,
                    "maximumRiskClass": closed_risk.value,
                },
                origin_type="authenticated_user",
            )
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.approval_authority",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=assignment_id,
                object_type="approval_authority_assignment",
                operation=operation.replace(".", "_"),
                metadata={"state": "active"},
            )
        )
        return ApprovalAuthorityView(assignment, transition)

    async def revoke(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        assignment_id: uuid.UUID,
        idempotency_key: str,
    ) -> ApprovalAuthorityView:
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=CollaborationAction.APPROVAL_AUTHORITY_REVOKE,
        )
        if not decision.allowed:
            raise CollaborationNotFoundError()
        _validate_idempotency_key(idempotency_key)
        view = await self.get(assignment_id=assignment_id, workspace_id=workspace_id)
        if view is None or view.transition.current_state != "active":
            raise CollaborationNotFoundError()
        request_digest = _digest(
            {"workspaceId": str(workspace_id), "assignmentId": str(assignment_id)}
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="approval_authority.revoke",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            replayed = await self.get(assignment_id=assignment_id, workspace_id=workspace_id)
            if replayed is None:
                raise CollaborationConflictError()
            return ApprovalAuthorityView(replayed.assignment, replayed.transition, duplicate=True)
        now = _aware_utc(self._now_factory())
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.approval_authority",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=assignment_id,
                object_type="approval_authority_assignment",
                operation="revoke_approval_authority",
            )
        )
        generation = await _increment_authority(
            self.session, workspace_id=workspace_id, trace_id=trace_id, now=now
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="approval_authority_assignment",
            subject_id=assignment_id,
            action="approval_authority.revoke",
            reason_code="approval_authority_revoked",
            trace_id=trace_id,
            metadata={"priorState": view.transition.current_state},
            now=now,
        )
        transition = CollaborationApprovalAuthorityTransition(
            transition_id=uuid.uuid4(),
            assignment_id=assignment_id,
            membership_id=view.assignment.membership_id,
            reviewer_user_id=view.assignment.reviewer_user_id,
            workspace_id=workspace_id,
            sequence=view.transition.sequence + 1,
            previous_state="active",
            current_state="revoked",
            reason_code="approval_authority_revoked",
            authority_generation=generation,
            actor_user_id=principal.user_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        request = _request_identity(
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="approval_authority.revoke",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_kind="approval_authority_assignment",
            result_id=assignment_id,
            trace_id=trace_id,
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        self.session.add_all((transition, request))
        await self.session.flush()
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise CollaborationNotFoundError()
        await self.events.record(
            CreateDomainEvent(
                event_type="approval_authority.revoked",
                user_id=workspace.owner_id,
                workspace_id=workspace_id,
                canvas_id=None,
                subject_id=assignment_id,
                actor_user_id=principal.user_id,
                source_identity=f"approval-authority:{assignment_id}:revoked",
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                payload={
                    "state": "revoked",
                    "reasonCode": "approval_authority_revoked",
                    "authorityGeneration": generation,
                },
                origin_type="authenticated_user",
            )
        )
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.approval_authority",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=assignment_id,
                object_type="approval_authority_assignment",
                operation="revoke_approval_authority",
                metadata={"state": "revoked"},
            )
        )
        return ApprovalAuthorityView(view.assignment, transition)

    async def get(
        self, *, assignment_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> ApprovalAuthorityView | None:
        latest = (
            select(func.max(CollaborationApprovalAuthorityTransition.sequence))
            .where(CollaborationApprovalAuthorityTransition.assignment_id == assignment_id)
            .scalar_subquery()
        )
        row = (
            await self.session.execute(
                select(
                    CollaborationApprovalAuthorityAssignment,
                    CollaborationApprovalAuthorityTransition,
                )
                .join(
                    CollaborationApprovalAuthorityTransition,
                    CollaborationApprovalAuthorityTransition.assignment_id
                    == CollaborationApprovalAuthorityAssignment.assignment_id,
                )
                .where(
                    CollaborationApprovalAuthorityAssignment.assignment_id == assignment_id,
                    CollaborationApprovalAuthorityAssignment.workspace_id == workspace_id,
                    CollaborationApprovalAuthorityTransition.sequence == latest,
                )
            )
        ).one_or_none()
        return ApprovalAuthorityView(row[0], row[1]) if row is not None else None

    async def evaluate_reviewer(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        requester_user_id: uuid.UUID,
        capability: Capability,
        resource_kind: ResourceKind,
        resource_id: uuid.UUID,
        risk_class: RiskClass,
        expected_authority_generation: int | None = None,
    ) -> ReviewerEligibilityDecision:
        if requester_user_id == principal.user_id or risk_class is RiskClass.R4_PROHIBITED:
            return ReviewerEligibilityDecision(False, "self_review_denied", None, None, None)
        membership = await self.memberships.resolve(
            user_id=principal.user_id,
            workspace_id=workspace_id,
            require_active=True,
        )
        authority = await self.session.get(WorkspaceAuthorityVersion, workspace_id)
        if membership is None or authority is None:
            return ReviewerEligibilityDecision(False, "authority_missing", None, None, None)
        if (
            expected_authority_generation is not None
            and expected_authority_generation != authority.authority_generation
        ):
            return ReviewerEligibilityDecision(
                False, "authority_stale", None, membership.membership.membership_id, None
            )
        latest = (
            select(func.max(CollaborationApprovalAuthorityTransition.sequence))
            .where(
                CollaborationApprovalAuthorityTransition.assignment_id
                == CollaborationApprovalAuthorityAssignment.assignment_id
            )
            .correlate(CollaborationApprovalAuthorityAssignment)
            .scalar_subquery()
        )
        now = _aware_utc(self._now_factory())
        rows = (
            await self.session.execute(
                select(
                    CollaborationApprovalAuthorityAssignment,
                    CollaborationApprovalAuthorityTransition,
                )
                .join(
                    CollaborationApprovalAuthorityTransition,
                    (
                        CollaborationApprovalAuthorityTransition.assignment_id
                        == CollaborationApprovalAuthorityAssignment.assignment_id
                    )
                    & (CollaborationApprovalAuthorityTransition.sequence == latest),
                )
                .where(
                    CollaborationApprovalAuthorityAssignment.workspace_id == workspace_id,
                    CollaborationApprovalAuthorityAssignment.membership_id
                    == membership.membership.membership_id,
                    CollaborationApprovalAuthorityAssignment.reviewer_user_id == principal.user_id,
                    CollaborationApprovalAuthorityAssignment.capability == capability.value,
                    CollaborationApprovalAuthorityAssignment.resource_kind == resource_kind.value,
                    CollaborationApprovalAuthorityAssignment.resource_id == resource_id,
                    CollaborationApprovalAuthorityAssignment.valid_from <= now,
                    CollaborationApprovalAuthorityAssignment.expires_at > now,
                    CollaborationApprovalAuthorityTransition.current_state == "active",
                )
                .order_by(CollaborationApprovalAuthorityAssignment.created_at.desc())
            )
        ).all()
        for assignment, _transition in rows:
            if _RISK_ORDER[risk_class] <= _RISK_ORDER[RiskClass(assignment.maximum_risk_class)]:
                return ReviewerEligibilityDecision(
                    True,
                    "eligible",
                    assignment.assignment_id,
                    membership.membership.membership_id,
                    authority.authority_generation,
                )
        return ReviewerEligibilityDecision(
            False,
            "assignment_missing",
            None,
            membership.membership.membership_id,
            authority.authority_generation,
        )

    async def record_reviewer_evidence(
        self,
        *,
        approval: ControlledAgentApproval,
        principal: Principal,
        assignment_id: uuid.UUID,
        capability: Capability,
        resource_kind: ResourceKind,
        resource_id: uuid.UUID,
        risk_class: RiskClass,
        decision_session_id: uuid.UUID,
        trace_id: uuid.UUID,
    ) -> CollaborationReviewerEligibilityEvidence:
        approved_capabilities = approval.payload.get("capabilities")
        approved_resources = approval.payload.get("resources")
        if (
            not isinstance(approved_capabilities, list)
            or capability.value not in approved_capabilities
            or not isinstance(approved_resources, list)
            or not any(
                isinstance(resource, dict)
                and resource.get("kind") == resource_kind.value
                and resource.get("resource_id") == str(resource_id)
                for resource in approved_resources
            )
        ):
            raise CollaborationNotFoundError()
        decision = await self.evaluate_reviewer(
            principal=principal,
            workspace_id=approval.workspace_id,
            requester_user_id=approval.user_id,
            capability=capability,
            resource_kind=resource_kind,
            resource_id=resource_id,
            risk_class=risk_class,
        )
        if not decision.allowed or decision.assignment_id != assignment_id:
            raise CollaborationNotFoundError()
        existing = await self.session.scalar(
            select(CollaborationReviewerEligibilityEvidence).where(
                CollaborationReviewerEligibilityEvidence.approval_id == approval.approval_id
            )
        )
        if existing is not None:
            if existing.assignment_id != assignment_id:
                raise CollaborationConflictError()
            return existing
        evidence = CollaborationReviewerEligibilityEvidence(
            eligibility_id=uuid.uuid4(),
            approval_id=approval.approval_id,
            execution_id=approval.execution_id,
            requester_user_id=approval.user_id,
            workspace_id=approval.workspace_id,
            deciding_user_id=principal.user_id,
            deciding_membership_id=cast(uuid.UUID, decision.membership_id),
            assignment_id=assignment_id,
            decision_session_id=decision_session_id,
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            authority_generation=cast(int, decision.authority_generation),
            scope_digest=_digest(
                {
                    "approvalId": str(approval.approval_id),
                    "assignmentId": str(assignment_id),
                    "reviewerUserId": str(principal.user_id),
                }
            ),
            trace_id=trace_id,
            recorded_at=_aware_utc(self._now_factory()),
        )
        self.session.add(evidence)
        await self.session.flush()
        return evidence


async def _increment_authority(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    trace_id: uuid.UUID,
    now: datetime,
) -> int:
    generation = await session.scalar(
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
        raise CollaborationConflictError()
    return generation


async def _request_replay(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    operation: str,
    idempotency_key: str,
    request_digest: str,
) -> CollaborationRequestIdentity | None:
    existing = await session.scalar(
        select(CollaborationRequestIdentity).where(
            CollaborationRequestIdentity.actor_user_id == actor_user_id,
            CollaborationRequestIdentity.workspace_id == workspace_id,
            CollaborationRequestIdentity.operation == operation,
            CollaborationRequestIdentity.idempotency_key == idempotency_key,
        )
    )
    if existing is not None and existing.request_digest != request_digest:
        raise CollaborationConflictError()
    return existing


def _request_identity(
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
        request_id=uuid.uuid5(workspace_id, f"{actor_user_id}:{operation}:{idempotency_key}"),
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


def _audit(
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    subject_kind: str,
    subject_id: uuid.UUID,
    action: str,
    reason_code: str,
    trace_id: uuid.UUID,
    metadata: dict[str, object],
    now: datetime,
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
        recorded_at=now,
    )


def _validate_idempotency_key(value: str) -> None:
    if not 8 <= len(value) <= 128 or not all(
        character.isalnum() or character in "._:-" for character in value
    ):
        raise CollaborationValidationError()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "ApprovalAuthorityService",
    "ApprovalAuthorityView",
    "MembershipAuthorityService",
    "ReviewerEligibilityDecision",
]
