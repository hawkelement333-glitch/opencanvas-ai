from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

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
    ResourceKind,
    ResourceScope,
    RiskClass,
    canonical_json,
    contract_digest,
)

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
USER_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")
EXECUTION_ID = uuid.UUID("30000000-0000-0000-0000-000000000003")
RESOURCE = ResourceScope(
    kind=ResourceKind.DOCUMENT_VERSION,
    resource_id=uuid.UUID("40000000-0000-0000-0000-000000000004"),
    version=7,
)


def make_context(*, resource: ResourceScope = RESOURCE) -> ContextSnapshot:
    return ContextSnapshot(
        snapshot_id=uuid.UUID("50000000-0000-0000-0000-000000000005"),
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        captured_at=NOW,
        resources=(ContextResource(scope=resource, content_digest="a" * 64),),
    )


def make_plan(*, resource: ResourceScope = RESOURCE) -> PlanSnapshot:
    return PlanSnapshot(
        plan_id=uuid.UUID("60000000-0000-0000-0000-000000000006"),
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        role=AgentRole.EVIDENCE_VERIFIER,
        created_at=NOW,
        actions=(
            PlanAction(
                action_id=uuid.UUID("70000000-0000-0000-0000-000000000007"),
                ordinal=0,
                capability=Capability.DOCUMENT_VERSION_READ,
                resource=resource,
                risk_class=RiskClass.R0_OBSERVATION,
            ),
        ),
    )


def test_canonical_serialization_and_hashing_are_stable() -> None:
    first = make_plan()
    equivalent = PlanSnapshot.model_validate(first.model_dump())

    assert canonical_json(first) == canonical_json(equivalent)
    assert contract_digest(first) == contract_digest(equivalent)
    assert '"created_at":"2026-07-21T12:00:00.000000Z"' in canonical_json(first)


def test_hash_changes_when_immutable_plan_or_context_changes() -> None:
    plan = make_plan()
    changed_resource = RESOURCE.model_copy(update={"version": 8})
    changed_plan = make_plan(resource=changed_resource)
    context = make_context()
    changed_context = make_context(resource=changed_resource)

    assert contract_digest(plan) != contract_digest(changed_plan)
    assert contract_digest(context) != contract_digest(changed_context)


def test_contracts_are_deeply_immutable() -> None:
    plan = make_plan()

    with pytest.raises(ValidationError):
        plan.role = AgentRole.DRAFTING_ASSISTANT  # type: ignore[misc]
    with pytest.raises(ValidationError):
        plan.actions[0].ordinal = 9  # type: ignore[misc]


def test_grants_and_approvals_canonicalize_unordered_scopes() -> None:
    second_resource = ResourceScope(kind=ResourceKind.CANVAS, resource_id=uuid.uuid4())
    context = make_context()
    plan = make_plan()
    grant = CapabilityGrant(
        grant_id=uuid.uuid4(),
        policy_version="policy-v1",
        issuing_service="policy-service",
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        role=AgentRole.EVIDENCE_VERIFIER,
        capabilities=(Capability.TRACE_SCOPED_READ, Capability.DOCUMENT_VERSION_READ),
        resources=(RESOURCE, second_resource),
        context_digest=contract_digest(context),
        plan_digest=contract_digest(plan),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    assert grant.capabilities == tuple(sorted(grant.capabilities, key=str))
    assert len(set(grant.resources)) == len(grant.resources)
    assert len(contract_digest(grant)) == 64


def test_naive_timestamps_and_unknown_capabilities_are_rejected() -> None:
    data = make_plan().model_dump()
    data["created_at"] = datetime(2026, 7, 21, 12)
    with pytest.raises(ValidationError, match="UTC offset"):
        PlanSnapshot.model_validate(data)

    action = make_plan().actions[0].model_dump()
    action["capability"] = "agent.anything.execute"
    with pytest.raises(ValidationError):
        PlanAction.model_validate(action)


def test_approval_binds_exact_grant_plan_context_and_scope() -> None:
    context = make_context()
    plan = make_plan()
    approval = ApprovalRecord(
        approval_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        policy_version="policy-v1",
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        execution_id=EXECUTION_ID,
        grant_id=uuid.uuid4(),
        decision=ApprovalDecision.APPROVED,
        capabilities=(Capability.DOCUMENT_VERSION_READ,),
        resources=(RESOURCE,),
        context_digest=contract_digest(context),
        plan_digest=contract_digest(plan),
        decided_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
    )

    assert approval.context_digest == contract_digest(context)
    assert approval.plan_digest == contract_digest(plan)
    assert len(contract_digest(approval)) == 64
