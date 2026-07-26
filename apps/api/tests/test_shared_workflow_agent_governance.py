from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    BoundedAgentInvocation,
    CollaborationAuditEvent,
    CollaborationAuthoritySnapshot,
    CollaborationResource,
    CollaborationResourceOwnershipTransition,
    ControlledWorkflowExecution,
    ControlledWorkflowVersion,
    DomainEventRecord,
    User,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agent_studio import BoundedAgentStudioService
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration_resources import (
    ShareAccessLevel,
    ShareAudienceKind,
    ShareResourceKind,
    ShareTarget,
    SharingService,
)
from opencanvas_api.services.workflows import ControlledWorkflowService, StartWorkflow
from tests.test_agent_studio import _active_agent
from tests.test_agent_studio import _service as _agent_service
from tests.test_controlled_workflows import _active_workflow
from tests.test_controlled_workflows import _service as _workflow_service


async def _add_member(database: Database, *, role: str = "member") -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    trace_id = uuid.uuid4()
    audit_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with database.sessions() as session:
        authority = await session.get(WorkspaceAuthorityVersion, SYSTEM_WORKSPACE_ID)
        assert authority is not None
        session.add(
            User(
                id=user_id,
                email=f"{user_id}@example.test",
                email_normalized=f"{user_id}@example.test",
                password_hash="test-only",
                display_name="Shared member",
                email_verified=True,
            )
        )
        session.add(
            CollaborationAuditEvent(
                audit_event_id=audit_id,
                workspace_id=SYSTEM_WORKSPACE_ID,
                actor_user_id=SYSTEM_USER_ID,
                subject_kind="workspace_membership",
                subject_id=membership_id,
                action="membership.test_admission",
                outcome="succeeded",
                reason_code="test_shared_governance",
                metadata_digest=hashlib.sha256(b"shared-member").hexdigest(),
                trace_id=trace_id,
                recorded_at=now,
            )
        )
        session.add(
            WorkspaceMembership(
                membership_id=membership_id,
                user_id=user_id,
                workspace_id=SYSTEM_WORKSPACE_ID,
                created_by_user_id=SYSTEM_USER_ID,
                accepted_invitation_id=None,
                collaboration_policy_version="collaboration-policy-v1",
                creation_trace_id=trace_id,
                creation_audit_event_id=audit_id,
                created_at=now,
            )
        )
        session.add(
            WorkspaceMembershipTransition(
                transition_id=uuid.uuid4(),
                membership_id=membership_id,
                user_id=user_id,
                workspace_id=SYSTEM_WORKSPACE_ID,
                sequence=0,
                previous_state=None,
                current_state="active",
                previous_role=None,
                current_role=role,
                reason_code="test_shared_governance",
                collaboration_policy_version="collaboration-policy-v1",
                authority_generation=authority.authority_generation,
                actor_user_id=SYSTEM_USER_ID,
                trace_id=trace_id,
                audit_event_id=audit_id,
                recorded_at=now,
            )
        )
        await session.commit()
    return user_id, membership_id


async def _share_execution_resources(
    database: Database,
    *,
    canvas_id: uuid.UUID,
    object_ids: tuple[uuid.UUID, ...],
    membership_id: uuid.UUID,
    workflow_definition_id: uuid.UUID,
    agent_id: uuid.UUID | None = None,
) -> None:
    async with database.sessions() as session:
        authority = await session.get(WorkspaceAuthorityVersion, SYSTEM_WORKSPACE_ID)
        owner_membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == SYSTEM_USER_ID,
                WorkspaceMembership.workspace_id == SYSTEM_WORKSPACE_ID,
            )
        )
        assert authority is not None and owner_membership is not None
        now = datetime.now(UTC)
        for object_id in object_ids:
            resource = await session.get(
                CollaborationResource,
                {
                    "resource_id": object_id,
                    "workspace_id": SYSTEM_WORKSPACE_ID,
                    "resource_kind": "canonical_object",
                },
            )
            if resource is None:
                session.add(
                    CollaborationResource(
                        resource_id=object_id,
                        workspace_id=SYSTEM_WORKSPACE_ID,
                        resource_kind="canonical_object",
                        canvas_id=None,
                        canonical_object_id=object_id,
                        workflow_definition_id=None,
                        agent_id=None,
                        target_user_id=None,
                        creator_user_id=SYSTEM_USER_ID,
                        creation_trace_id=uuid.uuid4(),
                        created_at=now,
                    )
                )
                session.add(
                    CollaborationResourceOwnershipTransition(
                        transition_id=uuid.uuid4(),
                        resource_id=object_id,
                        workspace_id=SYSTEM_WORKSPACE_ID,
                        resource_kind="canonical_object",
                        sequence=0,
                        previous_owner_kind=None,
                        previous_owner_membership_id=None,
                        previous_owner_user_id=None,
                        current_owner_kind="workspace",
                        current_owner_membership_id=None,
                        current_owner_user_id=None,
                        visibility_policy="private",
                        authority_generation=authority.authority_generation,
                        actor_user_id=SYSTEM_USER_ID,
                        actor_membership_id=owner_membership.membership_id,
                        reason_code="test_resource_registration",
                        trace_id=uuid.uuid4(),
                        audit_event_id=None,
                        recorded_at=now,
                    )
                )
        await session.flush()
        targets = [
            ShareTarget(
                resource_kind=ShareResourceKind.WORKFLOW,
                resource_id=workflow_definition_id,
                audience_kind=ShareAudienceKind.MEMBERSHIP,
                audience_membership_id=membership_id,
                access_level=ShareAccessLevel.VIEW,
            ),
            *[
                ShareTarget(
                    resource_kind=ShareResourceKind.CANONICAL_OBJECT,
                    resource_id=object_id,
                    audience_kind=ShareAudienceKind.MEMBERSHIP,
                    audience_membership_id=membership_id,
                    access_level=ShareAccessLevel.VIEW,
                )
                for object_id in object_ids
            ],
        ]
        if agent_id is not None:
            targets.append(
                ShareTarget(
                    resource_kind=ShareResourceKind.AGENT,
                    resource_id=agent_id,
                    audience_kind=ShareAudienceKind.MEMBERSHIP,
                    audience_membership_id=membership_id,
                    access_level=ShareAccessLevel.VIEW,
                )
            )
        await SharingService(session).create(
            principal=Principal(
                user_id=SYSTEM_USER_ID,
                email="owner@example.test",
                display_name="Owner",
                session_id=None,
                csrf_token_hash=None,
                synthetic=True,
            ),
            workspace_id=SYSTEM_WORKSPACE_ID,
            targets=targets,
            idempotency_key=f"shared-governance-{membership_id}",
        )
        await session.commit()


@pytest.mark.anyio
async def test_shared_member_invokes_owner_workflow_with_truthful_authority(
    database: Database,
) -> None:
    canvas_id, objects, version_id = await _active_workflow(database, include_bundle=False)
    user_id, membership_id = await _add_member(database)
    async with database.sessions() as session:
        version = await session.get(ControlledWorkflowVersion, version_id)
        assert version is not None
        definition_id = version.definition_id
    selected = (objects["note_one"], objects["note_two"])
    await _share_execution_resources(
        database,
        canvas_id=canvas_id,
        object_ids=selected,
        membership_id=membership_id,
        workflow_definition_id=definition_id,
    )
    async with database.sessions() as session:
        service: ControlledWorkflowService = _workflow_service(session)
        record = await service.start(
            StartWorkflow(
                user_id=user_id,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=version_id,
                query="First",
                selected_object_ids=selected,
                seed_object_ids=(objects["note_one"],),
                idempotency_key="shared-workflow-invoke",
            )
        )
        await session.commit()
        execution = record.execution
        assert execution.definition_owner_user_id == SYSTEM_USER_ID
        assert execution.user_id == user_id
        assert execution.invoking_membership_id == membership_id
        assert execution.authority_snapshot_id is not None
        snapshot = await session.get(
            CollaborationAuthoritySnapshot,
            execution.authority_snapshot_id,
        )
        assert snapshot is not None
        assert snapshot.permission == "workflow.invoke"
        assert snapshot.user_id == user_id
        assert snapshot.membership_id == membership_id
        audit = await session.scalar(
            select(CollaborationAuditEvent).where(
                CollaborationAuditEvent.trace_id == execution.trace_id,
                CollaborationAuditEvent.action == "workflow.invoke",
            )
        )
        assert audit is not None
        assert audit.actor_user_id == user_id
        assert audit.subject_id == definition_id
        event = await session.scalar(
            select(DomainEventRecord).where(
                DomainEventRecord.trace_id == execution.trace_id,
                DomainEventRecord.event_type == "workflow.execution.requested",
            )
        )
        assert event is not None
        assert event.actor_user_id == user_id
        assert event.audit_event_id == audit.audit_event_id


@pytest.mark.anyio
async def test_shared_member_invokes_owner_agent_without_owner_substitution(
    database: Database,
) -> None:
    canvas_id, objects, workflow_version_id, agent_id = await _active_agent(database)
    user_id, membership_id = await _add_member(database)
    async with database.sessions() as session:
        workflow = await session.get(ControlledWorkflowVersion, workflow_version_id)
        assert workflow is not None
    selected = (objects["note_one"], objects["note_two"])
    await _share_execution_resources(
        database,
        canvas_id=canvas_id,
        object_ids=selected,
        membership_id=membership_id,
        workflow_definition_id=workflow.definition_id,
        agent_id=agent_id,
    )
    async with database.sessions() as session:
        service: BoundedAgentStudioService = _agent_service(session)
        invocation, workflow_record = await service.invoke(
            user_id=user_id,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            agent_id=agent_id,
            workflow_version_id=workflow_version_id,
            query="First",
            selected_object_ids=selected,
            seed_object_ids=(objects["note_one"],),
            idempotency_key="shared-agent-invoke",
        )
        await session.commit()
        assert invocation.definition_owner_user_id == SYSTEM_USER_ID
        assert invocation.user_id == user_id
        assert invocation.invoking_membership_id == membership_id
        assert workflow_record.execution.user_id == user_id
        assert workflow_record.execution.definition_owner_user_id == SYSTEM_USER_ID
        snapshot = await session.get(
            CollaborationAuthoritySnapshot,
            invocation.authority_snapshot_id,
        )
        assert snapshot is not None
        assert snapshot.permission == "agent.invoke"
        assert snapshot.workflow_execution_id == workflow_record.execution.execution_id
        audit = await session.scalar(
            select(CollaborationAuditEvent).where(
                CollaborationAuditEvent.trace_id == invocation.trace_id,
                CollaborationAuditEvent.action == "agent.invoke",
            )
        )
        assert audit is not None
        assert audit.actor_user_id == user_id
        assert audit.subject_id == agent_id
        event = await session.scalar(
            select(DomainEventRecord).where(
                DomainEventRecord.trace_id == invocation.trace_id,
                DomainEventRecord.event_type == "agent.invocation.started",
            )
        )
        assert event is not None
        assert event.actor_user_id == user_id
        assert event.audit_event_id == audit.audit_event_id
        stored = await session.get(BoundedAgentInvocation, invocation.invocation_id)
        assert stored is not None
        execution = await session.get(
            ControlledWorkflowExecution,
            invocation.workflow_execution_id,
        )
        assert execution is not None
