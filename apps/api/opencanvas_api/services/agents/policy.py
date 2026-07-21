from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from opencanvas_api.services.agents.contracts import (
    ApprovalDecision,
    ApprovalRecord,
    Capability,
    CapabilityGrant,
    ContextSnapshot,
    ContractModel,
    PlanSnapshot,
    PolicyDecision,
    PolicyOutcome,
    ResourceScope,
    RevocationRecord,
    RiskClass,
    _require_aware_utc,
    contract_digest,
)


class PolicyRequest(ContractModel):
    decision_id: uuid.UUID
    policy_version: str = Field(min_length=1, max_length=64)
    evaluated_at: datetime
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    capability: Capability
    resource: ResourceScope
    context: ContextSnapshot
    plan: PlanSnapshot

    _evaluated_at_is_utc = field_validator("evaluated_at")(_require_aware_utc)


def evaluate_policy(
    request: PolicyRequest,
    *,
    grant: CapabilityGrant | None = None,
    approval: ApprovalRecord | None = None,
    revocations: tuple[RevocationRecord, ...] = (),
    consumed_approval_ids: frozenset[uuid.UUID] = frozenset(),
) -> PolicyDecision:
    """Evaluate one requested capability without I/O, mutation, or fallback authorization."""

    context_digest = contract_digest(request.context)
    plan_digest = contract_digest(request.plan)

    def decision(
        outcome: PolicyOutcome, reason_code: str, *, include_approval: bool = False
    ) -> PolicyDecision:
        return PolicyDecision(
            decision_id=request.decision_id,
            policy_version=request.policy_version,
            execution_id=request.execution_id,
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            outcome=outcome,
            reason_code=reason_code,
            evaluated_at=request.evaluated_at,
            grant_id=grant.grant_id if grant is not None else None,
            approval_id=(
                approval.approval_id if include_approval and approval is not None else None
            ),
            context_digest=context_digest,
            plan_digest=plan_digest,
        )

    if grant is None:
        return decision(PolicyOutcome.DENY, "grant_missing")
    if request.policy_version != grant.policy_version:
        return decision(PolicyOutcome.DENY, "policy_version_mismatch")
    if not _same_owner(request, grant):
        return decision(PolicyOutcome.DENY, "grant_scope_mismatch")
    if not _snapshots_belong_to_request(request):
        return decision(PolicyOutcome.DENY, "snapshot_scope_mismatch")
    if request.plan.role is not grant.role:
        return decision(PolicyOutcome.DENY, "grant_role_mismatch")
    matching_actions = tuple(
        action
        for action in request.plan.actions
        if action.capability is request.capability and action.resource == request.resource
    )
    if not matching_actions:
        return decision(PolicyOutcome.DENY, "action_not_in_plan")
    if any(action.risk_class is RiskClass.R4_PROHIBITED for action in matching_actions):
        return decision(PolicyOutcome.DENY, "action_prohibited")
    if request.evaluated_at < grant.issued_at or request.evaluated_at >= grant.expires_at:
        return decision(PolicyOutcome.DENY, "grant_inactive")
    if _is_revoked(grant.grant_id, "grant", request, revocations):
        return decision(PolicyOutcome.DENY, "grant_revoked")
    if context_digest != grant.context_digest or plan_digest != grant.plan_digest:
        return decision(PolicyOutcome.DENY, "grant_hash_mismatch")
    if request.capability not in grant.capabilities:
        return decision(PolicyOutcome.DENY, "capability_not_granted")
    if request.resource not in grant.resources:
        return decision(PolicyOutcome.DENY, "resource_not_granted")
    if not grant.approval_required:
        return decision(PolicyOutcome.ALLOW, "grant_valid")
    if approval is None:
        return decision(PolicyOutcome.APPROVAL_REQUIRED, "approval_missing")
    if grant.approval_id != approval.approval_id:
        return decision(PolicyOutcome.DENY, "approval_binding_mismatch")
    if approval.decision is not ApprovalDecision.APPROVED:
        return decision(PolicyOutcome.DENY, "approval_denied", include_approval=True)
    if not _same_owner(request, approval) or approval.grant_id != grant.grant_id:
        return decision(PolicyOutcome.DENY, "approval_scope_mismatch", include_approval=True)
    if request.policy_version != approval.policy_version:
        return decision(PolicyOutcome.DENY, "approval_policy_mismatch", include_approval=True)
    if request.evaluated_at < approval.decided_at or request.evaluated_at >= approval.expires_at:
        return decision(PolicyOutcome.DENY, "approval_inactive", include_approval=True)
    if _is_revoked(approval.approval_id, "approval", request, revocations):
        return decision(PolicyOutcome.DENY, "approval_revoked", include_approval=True)
    if approval.approval_id in consumed_approval_ids:
        return decision(PolicyOutcome.DENY, "approval_replayed", include_approval=True)
    if context_digest != approval.context_digest or plan_digest != approval.plan_digest:
        return decision(PolicyOutcome.DENY, "approval_hash_mismatch", include_approval=True)
    if approval.capabilities != grant.capabilities or approval.resources != grant.resources:
        return decision(PolicyOutcome.DENY, "approval_grant_mismatch", include_approval=True)
    return decision(PolicyOutcome.ALLOW, "approval_valid", include_approval=True)


def _same_owner(request: PolicyRequest, contract: CapabilityGrant | ApprovalRecord) -> bool:
    return (
        request.user_id == contract.user_id
        and request.workspace_id == contract.workspace_id
        and request.execution_id == contract.execution_id
    )


def _snapshots_belong_to_request(request: PolicyRequest) -> bool:
    expected = (request.user_id, request.workspace_id, request.execution_id)
    return expected == (
        request.context.user_id,
        request.context.workspace_id,
        request.context.execution_id,
    ) and expected == (
        request.plan.user_id,
        request.plan.workspace_id,
        request.plan.execution_id,
    )


def _is_revoked(
    subject_id: uuid.UUID,
    subject_kind: str,
    request: PolicyRequest,
    revocations: tuple[RevocationRecord, ...],
) -> bool:
    return any(
        record.subject_id == subject_id
        and record.subject_kind == subject_kind
        and record.user_id == request.user_id
        and record.workspace_id == request.workspace_id
        and record.execution_id == request.execution_id
        and record.revoked_at <= request.evaluated_at
        for record in revocations
    )


__all__ = ["PolicyRequest", "evaluate_policy"]
