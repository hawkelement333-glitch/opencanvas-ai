from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from opencanvas_api.db.models import SYSTEM_USER_ID, SYSTEM_WORKSPACE_ID
from opencanvas_api.services.agents.contracts import (
    AgentRole,
    ApprovalDecision,
    ApprovalRecord,
    Capability,
    CapabilityGrant,
    ContextResource,
    ContextSnapshot,
    ExecutionRecord,
    PlanAction,
    PlanSnapshot,
    ResourceKind,
    ResourceScope,
    RiskClass,
    contract_digest,
)

NOW = datetime(2026, 7, 21, 18, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class AgentBundle:
    execution: ExecutionRecord
    context: ContextSnapshot
    plan: PlanSnapshot
    grant: CapabilityGrant
    approval: ApprovalRecord
    resource: ResourceScope


def make_agent_bundle(
    *,
    user_id: uuid.UUID = SYSTEM_USER_ID,
    workspace_id: uuid.UUID = SYSTEM_WORKSPACE_ID,
    approval_expires_at: datetime | None = None,
) -> AgentBundle:
    execution_id = uuid.uuid4()
    resource = ResourceScope(
        kind=ResourceKind.DOCUMENT_VERSION,
        resource_id=uuid.uuid4(),
        version=3,
    )
    context = ContextSnapshot(
        snapshot_id=uuid.uuid4(),
        user_id=user_id,
        workspace_id=workspace_id,
        execution_id=execution_id,
        captured_at=NOW,
        resources=(ContextResource(scope=resource, content_digest="a" * 64),),
    )
    plan = PlanSnapshot(
        plan_id=uuid.uuid4(),
        user_id=user_id,
        workspace_id=workspace_id,
        execution_id=execution_id,
        role=AgentRole.EVIDENCE_VERIFIER,
        created_at=NOW,
        actions=(
            PlanAction(
                action_id=uuid.uuid4(),
                ordinal=0,
                capability=Capability.DOCUMENT_VERSION_READ,
                resource=resource,
                risk_class=RiskClass.R0_OBSERVATION,
            ),
        ),
    )
    approval_id = uuid.uuid4()
    grant = CapabilityGrant(
        grant_id=uuid.uuid4(),
        policy_version="policy-v1",
        issuing_service="controlled-agent-policy",
        user_id=user_id,
        workspace_id=workspace_id,
        execution_id=execution_id,
        role=AgentRole.EVIDENCE_VERIFIER,
        capabilities=(Capability.DOCUMENT_VERSION_READ,),
        resources=(resource,),
        context_digest=contract_digest(context),
        plan_digest=contract_digest(plan),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        approval_required=True,
        approval_id=approval_id,
    )
    approval = ApprovalRecord(
        approval_id=approval_id,
        session_id=uuid.uuid4(),
        policy_version=grant.policy_version,
        user_id=user_id,
        workspace_id=workspace_id,
        execution_id=execution_id,
        grant_id=grant.grant_id,
        decision=ApprovalDecision.APPROVED,
        capabilities=grant.capabilities,
        resources=grant.resources,
        context_digest=grant.context_digest,
        plan_digest=grant.plan_digest,
        decided_at=NOW,
        expires_at=approval_expires_at or NOW + timedelta(minutes=5),
    )
    execution = ExecutionRecord(
        execution_id=execution_id,
        user_id=user_id,
        workspace_id=workspace_id,
        role=AgentRole.EVIDENCE_VERIFIER,
        context_snapshot_id=context.snapshot_id,
        context_digest=contract_digest(context),
        plan_id=plan.plan_id,
        plan_digest=contract_digest(plan),
        grant_id=grant.grant_id,
        created_at=NOW,
    )
    return AgentBundle(execution, context, plan, grant, approval, resource)
