from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from opencanvas_api.services.agents.contracts import (
    AgentRole,
    ApprovalDecision,
    ApprovalRecord,
    Capability,
    CapabilityGrant,
    ContextResource,
    ContextSnapshot,
    PlanAction,
    PlanSnapshot,
    PolicyOutcome,
    ResourceKind,
    ResourceScope,
    RevocationRecord,
    RiskClass,
    contract_digest,
)
from opencanvas_api.services.agents.policy import PolicyRequest, evaluate_policy

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
USER_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")
EXECUTION_ID = uuid.UUID("30000000-0000-0000-0000-000000000003")
RESOURCE = ResourceScope(
    kind=ResourceKind.DOCUMENT_VERSION,
    resource_id=uuid.UUID("40000000-0000-0000-0000-000000000004"),
    version=7,
)


def fixtures() -> tuple[PolicyRequest, CapabilityGrant]:
    context = ContextSnapshot(
        snapshot_id=uuid.uuid4(),
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        captured_at=NOW,
        resources=(ContextResource(scope=RESOURCE, content_digest="a" * 64),),
    )
    plan = PlanSnapshot(
        plan_id=uuid.uuid4(),
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        role=AgentRole.EVIDENCE_VERIFIER,
        created_at=NOW,
        actions=(
            PlanAction(
                action_id=uuid.uuid4(),
                ordinal=0,
                capability=Capability.DOCUMENT_VERSION_READ,
                resource=RESOURCE,
                risk_class=RiskClass.R0_OBSERVATION,
            ),
        ),
    )
    request = PolicyRequest(
        decision_id=uuid.uuid4(),
        policy_version="policy-v1",
        evaluated_at=NOW + timedelta(seconds=10),
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        capability=Capability.DOCUMENT_VERSION_READ,
        resource=RESOURCE,
        context=context,
        plan=plan,
    )
    grant = CapabilityGrant(
        grant_id=uuid.uuid4(),
        policy_version="policy-v1",
        issuing_service="policy-service",
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        role=AgentRole.EVIDENCE_VERIFIER,
        capabilities=(Capability.DOCUMENT_VERSION_READ,),
        resources=(RESOURCE,),
        context_digest=contract_digest(context),
        plan_digest=contract_digest(plan),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    return request, grant


def test_policy_denies_by_default_and_allows_only_a_valid_grant() -> None:
    request, grant = fixtures()

    denied = evaluate_policy(request)
    allowed = evaluate_policy(request, grant=grant)

    assert (denied.outcome, denied.reason_code) == (PolicyOutcome.DENY, "grant_missing")
    assert (allowed.outcome, allowed.reason_code) == (PolicyOutcome.ALLOW, "grant_valid")


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("user_id", "grant_scope_mismatch"),
        ("workspace_id", "grant_scope_mismatch"),
        ("execution_id", "grant_scope_mismatch"),
    ],
)
def test_policy_denies_grants_for_the_wrong_owner_scope(field: str, reason: str) -> None:
    request, grant = fixtures()
    mismatched = grant.model_copy(update={field: uuid.uuid4()})

    result = evaluate_policy(request, grant=mismatched)

    assert (result.outcome, result.reason_code) == (PolicyOutcome.DENY, reason)


def test_policy_denies_wrong_capability_and_resource() -> None:
    request, grant = fixtures()
    other_resource = ResourceScope(kind=ResourceKind.DOCUMENT_VERSION, resource_id=uuid.uuid4())

    capability_result = evaluate_policy(
        request.model_copy(update={"capability": Capability.TRACE_SCOPED_READ}), grant=grant
    )
    resource_result = evaluate_policy(
        request.model_copy(update={"resource": other_resource}), grant=grant
    )

    assert capability_result.reason_code == "action_not_in_plan"
    assert resource_result.reason_code == "action_not_in_plan"


def test_policy_denies_role_mismatch_and_prohibited_plan_action() -> None:
    request, grant = fixtures()
    wrong_role = grant.model_copy(update={"role": AgentRole.DRAFTING_ASSISTANT})
    prohibited_action = request.plan.actions[0].model_copy(
        update={"risk_class": RiskClass.R4_PROHIBITED}
    )
    prohibited_plan = request.plan.model_copy(update={"actions": (prohibited_action,)})
    prohibited_request = request.model_copy(update={"plan": prohibited_plan})
    prohibited_grant = grant.model_copy(update={"plan_digest": contract_digest(prohibited_plan)})

    assert evaluate_policy(request, grant=wrong_role).reason_code == "grant_role_mismatch"
    assert (
        evaluate_policy(prohibited_request, grant=prohibited_grant).reason_code
        == "action_prohibited"
    )


def test_policy_denies_expired_and_revoked_grants() -> None:
    request, grant = fixtures()
    expired_request = request.model_copy(update={"evaluated_at": grant.expires_at})
    revocation = RevocationRecord(
        revocation_id=uuid.uuid4(),
        subject_kind="grant",
        subject_id=grant.grant_id,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        revoked_at=request.evaluated_at,
        reason_code="user_revoked",
    )

    assert evaluate_policy(expired_request, grant=grant).reason_code == "grant_inactive"
    assert evaluate_policy(request, grant=grant, revocations=(revocation,)).reason_code == (
        "grant_revoked"
    )


def test_policy_denies_altered_plan_and_context_hashes() -> None:
    request, grant = fixtures()
    changed_plan = request.plan.model_copy(update={"plan_id": uuid.uuid4()})
    changed_context = request.context.model_copy(update={"snapshot_id": uuid.uuid4()})

    assert (
        evaluate_policy(request.model_copy(update={"plan": changed_plan}), grant=grant).reason_code
        == "grant_hash_mismatch"
    )
    assert (
        evaluate_policy(
            request.model_copy(update={"context": changed_context}), grant=grant
        ).reason_code
        == "grant_hash_mismatch"
    )


def approval_fixtures() -> tuple[PolicyRequest, CapabilityGrant, ApprovalRecord]:
    request, base_grant = fixtures()
    approval_id = uuid.uuid4()
    grant = base_grant.model_copy(update={"approval_required": True, "approval_id": approval_id})
    approval = ApprovalRecord(
        approval_id=approval_id,
        session_id=uuid.uuid4(),
        policy_version=grant.policy_version,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        grant_id=grant.grant_id,
        decision=ApprovalDecision.APPROVED,
        capabilities=grant.capabilities,
        resources=grant.resources,
        context_digest=grant.context_digest,
        plan_digest=grant.plan_digest,
        decided_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
    )
    return request, grant, approval


def test_policy_requires_and_validates_exact_approval() -> None:
    request, grant, approval = approval_fixtures()

    missing = evaluate_policy(request, grant=grant)
    allowed = evaluate_policy(request, grant=grant, approval=approval)
    altered = approval.model_copy(update={"plan_digest": "f" * 64})

    assert missing.outcome is PolicyOutcome.APPROVAL_REQUIRED
    assert (allowed.outcome, allowed.reason_code) == (PolicyOutcome.ALLOW, "approval_valid")
    assert evaluate_policy(request, grant=grant, approval=altered).reason_code == (
        "approval_hash_mismatch"
    )


def test_policy_denies_expired_revoked_and_replayed_approvals() -> None:
    request, grant, approval = approval_fixtures()
    expired_request = request.model_copy(update={"evaluated_at": approval.expires_at})
    revocation = RevocationRecord(
        revocation_id=uuid.uuid4(),
        subject_kind="approval",
        subject_id=approval.approval_id,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        revoked_at=request.evaluated_at,
        reason_code="user_revoked",
    )

    assert (
        evaluate_policy(expired_request, grant=grant, approval=approval).reason_code
        == "approval_inactive"
    )
    assert (
        evaluate_policy(
            request, grant=grant, approval=approval, revocations=(revocation,)
        ).reason_code
        == "approval_revoked"
    )
    assert (
        evaluate_policy(
            request,
            grant=grant,
            approval=approval,
            consumed_approval_ids=frozenset({approval.approval_id}),
        ).reason_code
        == "approval_replayed"
    )


def test_policy_evaluation_is_side_effect_free() -> None:
    request, grant, approval = approval_fixtures()
    request_before = request.model_dump()
    grant_before = grant.model_dump()
    approval_before = approval.model_dump()
    consumed = frozenset[uuid.UUID]()

    first = evaluate_policy(request, grant=grant, approval=approval, consumed_approval_ids=consumed)
    second = evaluate_policy(
        request, grant=grant, approval=approval, consumed_approval_ids=consumed
    )

    assert first == second
    assert request.model_dump() == request_before
    assert grant.model_dump() == grant_before
    assert approval.model_dump() == approval_before
    assert consumed == frozenset()
