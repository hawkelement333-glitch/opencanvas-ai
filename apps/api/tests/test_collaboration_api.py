from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    CollaborationAuditEvent,
    CollaborationRequestIdentity,
    DomainActivityEntry,
    DomainEventOutbox,
    DomainEventRecord,
    User,
    WorkspaceAuthorityVersion,
    WorkspaceInvitation,
    WorkspaceInvitationSecretVersion,
    WorkspaceInvitationTransition,
    WorkspaceMembership,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import Capability, ResourceKind, RiskClass
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration import (
    INVITATION_DEFAULT_DAYS,
    INVITATION_MAX_DAYS,
    MEMBERSHIP_LIMIT_PER_WORKSPACE,
    PAGE_DEFAULT,
    PAGE_MAX,
    PENDING_INVITATION_LIMIT_PER_WORKSPACE,
)
from opencanvas_api.services.collaboration_management import ApprovalAuthorityService
from opencanvas_api.services.domain_events import DomainEventOutboxService

JsonObject = dict[str, Any]


def _enable_real_auth(app: FastAPI) -> Settings:
    current = cast(Settings, app.dependency_overrides[get_settings]())
    settings = current.model_copy(
        update={
            "auth_test_bypass": False,
            "session_secret": "test-session-secret-that-is-long-enough-2026",
            "invitation_secret": "test-invitation-secret-that-is-distinct-2026",
            "auth_requests_per_ip_per_minute": 100,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


async def _sign_up(
    client: httpx.AsyncClient,
    prefix: str,
    *,
    email: str,
    display_name: str,
) -> JsonObject:
    response = await client.post(
        f"{prefix}/auth/signup",
        json={
            "email": email,
            "password": "Correct-Horse-2026",
            "displayName": display_name,
        },
    )
    assert response.status_code == 201, response.text
    return cast(JsonObject, response.json())


def _csrf(session: JsonObject) -> dict[str, str]:
    return {"X-CSRF-Token": cast(str, session["csrfToken"])}


async def _workspace(client: httpx.AsyncClient, prefix: str) -> JsonObject:
    response = await client.get(f"{prefix}/workspaces")
    assert response.status_code == 200, response.text
    workspaces = cast(list[JsonObject], response.json())
    assert len(workspaces) == 1
    return workspaces[0]


@pytest.mark.security
async def test_invitation_acceptance_is_scoped_idempotent_and_traceable(
    app: FastAPI,
    database: Database,
    api_prefix: str,
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as owner,
        httpx.AsyncClient(transport=transport, base_url="http://test") as recipient,
        httpx.AsyncClient(transport=transport, base_url="http://test") as attacker,
    ):
        owner_session = await _sign_up(
            owner,
            api_prefix,
            email="owner-collaboration@example.test",
            display_name="Owner",
        )
        recipient_session = await _sign_up(
            recipient,
            api_prefix,
            email="recipient-collaboration@example.test",
            display_name="Recipient",
        )
        attacker_session = await _sign_up(
            attacker,
            api_prefix,
            email="attacker-collaboration@example.test",
            display_name="Attacker",
        )
        owner_workspace = await _workspace(owner, api_prefix)

        missing_csrf = await owner.post(
            f"{api_prefix}/workspaces/{owner_workspace['id']}/invitations",
            json={
                "recipientEmail": "recipient-collaboration@example.test",
                "intendedRole": "editor",
                "idempotencyKey": "invite-create-001",
            },
        )
        assert missing_csrf.status_code == 403

        created = await owner.post(
            f"{api_prefix}/workspaces/{owner_workspace['id']}/invitations",
            json={
                "recipientEmail": "Recipient-Collaboration@Example.Test",
                "intendedRole": "editor",
                "idempotencyKey": "invite-create-001",
            },
            headers=_csrf(owner_session),
        )
        assert created.status_code == 201, created.text
        invitation = cast(JsonObject, created.json())
        token = cast(str, invitation["developmentToken"])
        assert token
        assert invitation["recipientEmailMasked"] == "r***@example.test"
        assert invitation["state"] == "pending"
        invitation_id = cast(str, invitation["invitationId"])

        duplicate = await owner.post(
            f"{api_prefix}/workspaces/{owner_workspace['id']}/invitations",
            json={
                "recipientEmail": "recipient-collaboration@example.test",
                "intendedRole": "editor",
                "idempotencyKey": "invite-create-001",
            },
            headers=_csrf(owner_session),
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["invitationId"] == invitation_id
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["developmentToken"] is None

        cross_tenant_list = await recipient.get(
            f"{api_prefix}/workspaces/{owner_workspace['id']}/invitations"
        )
        assert cross_tenant_list.status_code == 404
        listed = await owner.get(f"{api_prefix}/workspaces/{owner_workspace['id']}/invitations")
        assert listed.status_code == 200
        assert listed.json()[0]["recipientEmailMasked"] == "r***@example.test"
        assert "developmentToken" not in listed.json()[0] or (
            listed.json()[0]["developmentToken"] is None
        )

        wrong_recipient = await attacker.post(
            f"{api_prefix}/collaboration-invitations/{invitation_id}/accept",
            json={"token": token, "idempotencyKey": "invite-accept-001"},
            headers=_csrf(attacker_session),
        )
        assert wrong_recipient.status_code == 404
        assert token not in wrong_recipient.text

        accepted = await recipient.post(
            f"{api_prefix}/collaboration-invitations/{invitation_id}/accept",
            json={"token": token, "idempotencyKey": "invite-accept-001"},
            headers=_csrf(recipient_session),
        )
        assert accepted.status_code == 200, accepted.text
        membership = accepted.json()
        assert membership["workspaceId"] == owner_workspace["id"]
        assert membership["role"] == "editor"
        assert membership["state"] == "active"
        assert membership["authorityGeneration"] == 2

        replay = await recipient.post(
            f"{api_prefix}/collaboration-invitations/{invitation_id}/accept",
            json={"token": token, "idempotencyKey": "invite-accept-001"},
            headers=_csrf(recipient_session),
        )
        assert replay.status_code == 200
        assert replay.json()["membershipId"] == membership["membershipId"]

        recipient_workspaces = (await recipient.get(f"{api_prefix}/workspaces")).json()
        assert owner_workspace["id"] in {item["id"] for item in recipient_workspaces}

    async with database.sessions() as session:
        invitation_record = await session.get(WorkspaceInvitation, uuid.UUID(invitation_id))
        assert invitation_record is not None
        assert token not in invitation_record.recipient_email_normalized
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceInvitationSecretVersion)
                .where(
                    WorkspaceInvitationSecretVersion.invitation_id
                    == invitation_record.invitation_id
                )
            )
            == 1
        )
        outbox = DomainEventOutboxService(session)
        while await outbox.process_one(owner_id="collaboration-test-projector"):
            pass
        await session.commit()
        activity_types = set(
            (
                await session.scalars(
                    select(DomainActivityEntry.event_type).where(
                        DomainActivityEntry.workspace_id == invitation_record.workspace_id
                    )
                )
            ).all()
        )
        assert {
            "invitation.created",
            "invitation.accepted",
            "membership.activated",
        } <= activity_types
        secret_hash = await session.scalar(
            select(WorkspaceInvitationSecretVersion.token_hash).where(
                WorkspaceInvitationSecretVersion.invitation_id == invitation_record.invitation_id
            )
        )
        assert secret_hash is not None and token not in secret_hash
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(
                    WorkspaceMembership.accepted_invitation_id == invitation_record.invitation_id
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceInvitationTransition)
                .where(
                    WorkspaceInvitationTransition.invitation_id == invitation_record.invitation_id,
                    WorkspaceInvitationTransition.current_state == "accepted",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(WorkspaceAuthorityVersion.authority_generation).where(
                    WorkspaceAuthorityVersion.workspace_id == invitation_record.workspace_id
                )
            )
            == 2
        )
        event_types = set(
            (
                await session.scalars(
                    select(DomainEventRecord.event_type).where(
                        DomainEventRecord.workspace_id == invitation_record.workspace_id
                    )
                )
            ).all()
        )
        assert {
            "invitation.created",
            "invitation.accepted",
            "membership.activated",
        } <= event_types
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DomainEventOutbox)
                .where(DomainEventOutbox.workspace_id == invitation_record.workspace_id)
            )
            >= 3
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationAuditEvent)
                .where(CollaborationAuditEvent.workspace_id == invitation_record.workspace_id)
            )
            >= 4
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationRequestIdentity)
                .where(
                    CollaborationRequestIdentity.workspace_id == invitation_record.workspace_id,
                    CollaborationRequestIdentity.operation == "invitation.accept",
                )
            )
            == 1
        )


@pytest.mark.security
async def test_revocation_decline_rotation_and_safe_errors(
    app: FastAPI,
    api_prefix: str,
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as owner,
        httpx.AsyncClient(transport=transport, base_url="http://test") as recipient,
    ):
        owner_session = await _sign_up(
            owner,
            api_prefix,
            email="lifecycle-owner@example.test",
            display_name="Lifecycle owner",
        )
        recipient_session = await _sign_up(
            recipient,
            api_prefix,
            email="lifecycle-recipient@example.test",
            display_name="Lifecycle recipient",
        )
        workspace = await _workspace(owner, api_prefix)

        first = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/invitations",
            json={
                "recipientEmail": "lifecycle-recipient@example.test",
                "intendedRole": "viewer",
                "idempotencyKey": "lifecycle-create-001",
            },
            headers=_csrf(owner_session),
        )
        assert first.status_code == 201
        first_data = first.json()
        revoked = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/invitations/"
            f"{first_data['invitationId']}/revoke",
            json={"idempotencyKey": "lifecycle-revoke-001"},
            headers=_csrf(owner_session),
        )
        assert revoked.status_code == 200
        assert revoked.json()["state"] == "revoked"
        revoked_accept = await recipient.post(
            f"{api_prefix}/collaboration-invitations/{first_data['invitationId']}/accept",
            json={
                "token": first_data["developmentToken"],
                "idempotencyKey": "lifecycle-accept-001",
            },
            headers=_csrf(recipient_session),
        )
        assert revoked_accept.status_code == 404

        second = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/invitations",
            json={
                "recipientEmail": "lifecycle-recipient@example.test",
                "intendedRole": "member",
                "idempotencyKey": "lifecycle-create-002",
            },
            headers=_csrf(owner_session),
        )
        assert second.status_code == 201
        second_data = second.json()
        declined = await recipient.post(
            f"{api_prefix}/collaboration-invitations/{second_data['invitationId']}/decline",
            json={
                "token": second_data["developmentToken"],
                "idempotencyKey": "lifecycle-decline-001",
            },
            headers=_csrf(recipient_session),
        )
        assert declined.status_code == 200
        assert declined.json()["state"] == "declined"
        declined_accept = await recipient.post(
            f"{api_prefix}/collaboration-invitations/{second_data['invitationId']}/accept",
            json={
                "token": second_data["developmentToken"],
                "idempotencyKey": "lifecycle-accept-002",
            },
            headers=_csrf(recipient_session),
        )
        assert declined_accept.status_code == 404

        collision = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/invitations",
            json={
                "recipientEmail": "another@example.test",
                "intendedRole": "viewer",
                "idempotencyKey": "lifecycle-create-002",
            },
            headers=_csrf(owner_session),
        )
        assert collision.status_code == 409
        assert "another@example.test" not in collision.text


def test_server_owned_collaboration_limits_are_fixed() -> None:
    assert MEMBERSHIP_LIMIT_PER_WORKSPACE == 500
    assert PENDING_INVITATION_LIMIT_PER_WORKSPACE == 100
    assert INVITATION_DEFAULT_DAYS == 7
    assert INVITATION_MAX_DAYS == 30
    assert PAGE_DEFAULT == 50
    assert PAGE_MAX == 100


@pytest.mark.security
async def test_concurrent_duplicate_acceptance_creates_one_membership(
    app: FastAPI,
    database: Database,
    api_prefix: str,
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as owner,
        httpx.AsyncClient(transport=transport, base_url="http://test") as recipient,
    ):
        owner_session = await _sign_up(
            owner,
            api_prefix,
            email="concurrent-owner@example.test",
            display_name="Concurrent owner",
        )
        recipient_session = await _sign_up(
            recipient,
            api_prefix,
            email="concurrent-recipient@example.test",
            display_name="Concurrent recipient",
        )
        workspace = await _workspace(owner, api_prefix)
        created = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/invitations",
            json={
                "recipientEmail": "concurrent-recipient@example.test",
                "intendedRole": "member",
                "idempotencyKey": "concurrent-create-001",
            },
            headers=_csrf(owner_session),
        )
        invitation = created.json()
        path = f"{api_prefix}/collaboration-invitations/{invitation['invitationId']}/accept"
        body = {
            "token": invitation["developmentToken"],
            "idempotencyKey": "concurrent-accept-001",
        }
        first, second = await asyncio.gather(
            recipient.post(path, json=body, headers=_csrf(recipient_session)),
            recipient.post(path, json=body, headers=_csrf(recipient_session)),
        )
        assert {first.status_code, second.status_code} <= {200, 409}
        assert 200 in {first.status_code, second.status_code}

    async with database.sessions() as session:
        invitation_id = uuid.UUID(invitation["invitationId"])
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.accepted_invitation_id == invitation_id)
            )
            == 1
        )


@pytest.mark.security
async def test_roles_lifecycle_and_approval_authority_are_scoped_and_idempotent(
    app: FastAPI,
    database: Database,
    api_prefix: str,
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as owner,
        httpx.AsyncClient(transport=transport, base_url="http://test") as administrator,
        httpx.AsyncClient(transport=transport, base_url="http://test") as approver,
    ):
        owner_session = await _sign_up(
            owner,
            api_prefix,
            email="authority-owner@example.test",
            display_name="Authority owner",
        )
        administrator_session = await _sign_up(
            administrator,
            api_prefix,
            email="authority-admin@example.test",
            display_name="Authority administrator",
        )
        approver_session = await _sign_up(
            approver,
            api_prefix,
            email="authority-approver@example.test",
            display_name="Authority approver",
        )
        workspace = await _workspace(owner, api_prefix)

        async def invite_and_accept(
            *,
            client: httpx.AsyncClient,
            session: JsonObject,
            email: str,
            role: str,
            key: str,
        ) -> JsonObject:
            created = await owner.post(
                f"{api_prefix}/workspaces/{workspace['id']}/invitations",
                json={
                    "recipientEmail": email,
                    "intendedRole": role,
                    "idempotencyKey": f"{key}-create",
                },
                headers=_csrf(owner_session),
            )
            assert created.status_code == 201, created.text
            invitation = created.json()
            accepted = await client.post(
                f"{api_prefix}/collaboration-invitations/{invitation['invitationId']}/accept",
                json={
                    "token": invitation["developmentToken"],
                    "idempotencyKey": f"{key}-accept",
                },
                headers=_csrf(session),
            )
            assert accepted.status_code == 200, accepted.text
            return cast(JsonObject, accepted.json())

        admin_membership = await invite_and_accept(
            client=administrator,
            session=administrator_session,
            email="authority-admin@example.test",
            role="administrator",
            key="authority-admin",
        )
        approver_membership = await invite_and_accept(
            client=approver,
            session=approver_session,
            email="authority-approver@example.test",
            role="approver",
            key="authority-approver",
        )

        admin_list = await administrator.get(
            f"{api_prefix}/workspaces/{workspace['id']}/memberships"
        )
        assert admin_list.status_code == 200
        assert len(admin_list.json()) == 3
        owner_membership = next(item for item in admin_list.json() if item["role"] == "owner")
        protected_owner = await administrator.post(
            f"{api_prefix}/workspaces/{workspace['id']}/memberships/"
            f"{owner_membership['membershipId']}/role",
            json={"role": "viewer", "idempotencyKey": "owner-demotion-denied"},
            headers=_csrf(administrator_session),
        )
        assert protected_owner.status_code == 404

        assigned = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/approval-authority",
            json={
                "membershipId": approver_membership["membershipId"],
                "capability": "workspace.metadata.read",
                "resourceKind": "workspace",
                "resourceId": workspace["id"],
                "maximumRiskClass": "r3_durable_write",
                "expiresInDays": 7,
                "idempotencyKey": "approval-authority-assign",
            },
            headers=_csrf(owner_session),
        )
        assert assigned.status_code == 201, assigned.text
        assignment = assigned.json()
        assert assignment["state"] == "active"
        duplicate = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/approval-authority",
            json={
                "membershipId": approver_membership["membershipId"],
                "capability": "workspace.metadata.read",
                "resourceKind": "workspace",
                "resourceId": workspace["id"],
                "maximumRiskClass": "r3_durable_write",
                "expiresInDays": 7,
                "idempotencyKey": "approval-authority-assign",
            },
            headers=_csrf(owner_session),
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["assignmentId"] == assignment["assignmentId"]
        assert duplicate.json()["duplicate"] is True
        async with database.sessions() as eligibility_session:
            reviewer = await eligibility_session.scalar(
                select(User).where(User.email_normalized == "authority-approver@example.test")
            )
            assert reviewer is not None
            reviewer_principal = Principal(
                user_id=reviewer.id,
                email=reviewer.email_normalized,
                display_name=reviewer.display_name,
                session_id=uuid.uuid4(),
                csrf_token_hash="test-csrf",
            )
            eligible = await ApprovalAuthorityService(eligibility_session).evaluate_reviewer(
                principal=reviewer_principal,
                workspace_id=uuid.UUID(workspace["id"]),
                requester_user_id=uuid.UUID(owner_session["user"]["id"]),
                capability=Capability.WORKSPACE_METADATA_READ,
                resource_kind=ResourceKind.WORKSPACE,
                resource_id=uuid.UUID(workspace["id"]),
                risk_class=RiskClass.R3_DURABLE_WRITE,
            )
            assert eligible.allowed is True
            wrong_scope = await ApprovalAuthorityService(eligibility_session).evaluate_reviewer(
                principal=reviewer_principal,
                workspace_id=uuid.UUID(workspace["id"]),
                requester_user_id=uuid.UUID(owner_session["user"]["id"]),
                capability=Capability.WORKSPACE_METADATA_READ,
                resource_kind=ResourceKind.WORKSPACE,
                resource_id=uuid.uuid4(),
                risk_class=RiskClass.R3_DURABLE_WRITE,
            )
            assert wrong_scope.allowed is False

        self_assignment = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/approval-authority",
            json={
                "membershipId": owner_membership["membershipId"],
                "capability": "workspace.metadata.read",
                "resourceKind": "workspace",
                "resourceId": workspace["id"],
                "maximumRiskClass": "r3_durable_write",
                "expiresInDays": 7,
                "idempotencyKey": "approval-self-denied",
            },
            headers=_csrf(owner_session),
        )
        assert self_assignment.status_code == 404

        suspended = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/memberships/"
            f"{admin_membership['membershipId']}/suspend",
            json={"idempotencyKey": "admin-suspend-001"},
            headers=_csrf(owner_session),
        )
        assert suspended.status_code == 200
        assert suspended.json()["state"] == "suspended"
        denied_after_suspend = await administrator.get(
            f"{api_prefix}/workspaces/{workspace['id']}/memberships"
        )
        assert denied_after_suspend.status_code == 404
        restored = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/memberships/"
            f"{admin_membership['membershipId']}/restore",
            json={"idempotencyKey": "admin-restore-001"},
            headers=_csrf(owner_session),
        )
        assert restored.status_code == 200
        assert restored.json()["state"] == "active"

        revoked = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/approval-authority/"
            f"{assignment['assignmentId']}/revoke",
            json={"idempotencyKey": "approval-authority-revoke"},
            headers=_csrf(owner_session),
        )
        assert revoked.status_code == 200
        assert revoked.json()["state"] == "revoked"
        role_path = (
            f"{api_prefix}/workspaces/{workspace['id']}/memberships/"
            f"{approver_membership['membershipId']}/role"
        )
        role_body = {"role": "member", "idempotencyKey": "approver-role-change"}
        changed_first, changed_second = await asyncio.gather(
            owner.post(role_path, json=role_body, headers=_csrf(owner_session)),
            owner.post(role_path, json=role_body, headers=_csrf(owner_session)),
        )
        assert {changed_first.status_code, changed_second.status_code} <= {200, 409}
        assert 200 in {changed_first.status_code, changed_second.status_code}
        changed = (
            changed_first if changed_first.status_code == 200 else changed_second
        )
        assert changed.json()["role"] == "member"
        role_replay = await owner.post(
            role_path,
            json=role_body,
            headers=_csrf(owner_session),
        )
        assert role_replay.status_code == 200
        removed = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/memberships/"
            f"{admin_membership['membershipId']}/remove",
            json={"idempotencyKey": "admin-remove-001"},
            headers=_csrf(owner_session),
        )
        assert removed.status_code == 200
        assert removed.json()["state"] == "removed"

    async with database.sessions() as session:
        assert (
            await session.scalar(
                select(WorkspaceAuthorityVersion.authority_generation).where(
                    WorkspaceAuthorityVersion.workspace_id == uuid.UUID(workspace["id"])
                )
            )
            == 9
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DomainEventRecord)
                .where(
                    DomainEventRecord.workspace_id == uuid.UUID(workspace["id"]),
                    DomainEventRecord.event_type.in_(
                        (
                            "membership.suspended",
                            "membership.restored",
                            "approval_authority.assigned",
                            "approval_authority.revoked",
                            "membership.role_changed",
                            "membership.removed",
                        )
                    ),
                )
            )
            == 6
        )
        outbox = DomainEventOutboxService(session)
        while await outbox.process_one(owner_id="collaboration-authority-test-projector"):
            pass
        await session.commit()
        activity_types = set(
            (
                await session.scalars(
                    select(DomainActivityEntry.event_type).where(
                        DomainActivityEntry.workspace_id == uuid.UUID(workspace["id"])
                    )
                )
            ).all()
        )
        assert {
            "membership.suspended",
            "membership.restored",
            "approval_authority.assigned",
            "approval_authority.revoked",
            "membership.role_changed",
            "membership.removed",
        } <= activity_types
