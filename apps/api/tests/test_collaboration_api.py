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
    WorkspaceAuthorityVersion,
    WorkspaceInvitation,
    WorkspaceInvitationSecretVersion,
    WorkspaceInvitationTransition,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.collaboration import (
    INVITATION_DEFAULT_DAYS,
    INVITATION_MAX_DAYS,
    MEMBERSHIP_LIMIT_PER_WORKSPACE,
    PAGE_DEFAULT,
    PAGE_MAX,
    PENDING_INVITATION_LIMIT_PER_WORKSPACE,
)
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
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembershipTransition)
                .join(
                    WorkspaceMembership,
                    WorkspaceMembership.membership_id
                    == WorkspaceMembershipTransition.membership_id,
                )
                .where(
                    WorkspaceMembership.accepted_invitation_id == invitation_id,
                    WorkspaceMembershipTransition.current_state == "active",
                )
            )
            == 1
        )
