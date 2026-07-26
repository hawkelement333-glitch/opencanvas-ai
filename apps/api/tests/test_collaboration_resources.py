from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update

from opencanvas_api.db.models import (
    CollaborationAuthoritySnapshot,
    CollaborationOwnershipTransfer,
    CollaborationResource,
    CollaborationResourceOwnershipTransition,
    CollaborationResourceShare,
    CollaborationResourceShareTransition,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration import CollaborationNotFoundError
from opencanvas_api.services.collaboration_authority import CollaborationPermission
from opencanvas_api.services.collaboration_resources import (
    AuthorityBoundary,
    RevocationFenceService,
)
from tests.test_collaboration_api import (
    _csrf,
    _enable_real_auth,
    _sign_up,
    _workspace,
)

JsonObject = dict[str, Any]


@pytest.mark.security
async def test_typed_canvas_share_and_revocation_execute_once(
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
            email="owner-sharing@example.test",
            display_name="Sharing owner",
        )
        recipient_session = await _sign_up(
            recipient,
            api_prefix,
            email="recipient-sharing@example.test",
            display_name="Sharing recipient",
        )
        workspace = await _workspace(owner, api_prefix)
        canvas_response = await owner.post(
            f"{api_prefix}/canvases",
            json={"name": "Shared canvas", "workspaceId": workspace["id"]},
            headers=_csrf(owner_session),
        )
        assert canvas_response.status_code == 201, canvas_response.text
        canvas = cast(JsonObject, canvas_response.json())

        invitation_response = await owner.post(
            f"{api_prefix}/workspaces/{workspace['id']}/invitations",
            json={
                "recipientEmail": "recipient-sharing@example.test",
                "intendedRole": "administrator",
                "idempotencyKey": "share-invite-create-001",
            },
            headers=_csrf(owner_session),
        )
        assert invitation_response.status_code == 201, invitation_response.text
        invitation = cast(JsonObject, invitation_response.json())
        acceptance = await recipient.post(
            f"{api_prefix}/collaboration-invitations/{invitation['invitationId']}/accept",
            json={
                "token": invitation["developmentToken"],
                "idempotencyKey": "share-invite-accept-001",
            },
            headers=_csrf(recipient_session),
        )
        assert acceptance.status_code == 200, acceptance.text
        recipient_membership = cast(JsonObject, acceptance.json())

        workspace_id = uuid.UUID(cast(str, workspace["id"]))
        canvas_id = uuid.UUID(cast(str, canvas["id"]))
        async with database.sessions() as session:
            authority = await session.get(WorkspaceAuthorityVersion, workspace_id)
            owner_membership = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id
                    == uuid.UUID(cast(str, owner_session["user"]["id"])),
                )
            )
            assert authority is not None and owner_membership is not None
            now = datetime.now(UTC)
            session.add(
                CollaborationResource(
                    resource_id=canvas_id,
                    workspace_id=workspace_id,
                    resource_kind="canvas",
                    canvas_id=canvas_id,
                    creator_user_id=owner_membership.user_id,
                    creation_trace_id=uuid.uuid4(),
                    created_at=now,
                )
            )
            session.add(
                CollaborationResourceOwnershipTransition(
                    transition_id=uuid.uuid4(),
                    resource_id=canvas_id,
                    workspace_id=workspace_id,
                    resource_kind="canvas",
                    sequence=0,
                    previous_owner_kind=None,
                    current_owner_kind="workspace",
                    visibility_policy="private",
                    authority_generation=authority.authority_generation,
                    actor_user_id=owner_membership.user_id,
                    actor_membership_id=owner_membership.membership_id,
                    reason_code="resource_registered",
                    trace_id=uuid.uuid4(),
                    recorded_at=now,
                )
            )
            await session.commit()

        share_payload = {
            "targets": [
                {
                    "resourceKind": "canvas",
                    "resourceId": str(canvas_id),
                    "audienceKind": "membership",
                    "audienceMembershipId": recipient_membership["membershipId"],
                    "accessLevel": "contribute",
                }
            ],
            "idempotencyKey": "canvas-share-create-001",
        }
        created = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/shares",
            json=share_payload,
            headers=_csrf(owner_session),
        )
        assert created.status_code == 201, created.text
        share = cast(JsonObject, created.json()[0])
        assert share["state"] == "active"
        assert share["accessLevel"] == "contribute"

        replay = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/shares",
            json=share_payload,
            headers=_csrf(owner_session),
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()[0]["shareId"] == share["shareId"]
        assert replay.json()[0]["duplicate"] is True

        async with database.sessions() as session:
            snapshot = await RevocationFenceService(session).capture(
                principal=Principal(
                    user_id=uuid.UUID(cast(str, owner_session["user"]["id"])),
                    email="owner-sharing@example.test",
                    display_name="Sharing owner",
                    session_id=None,
                    csrf_token_hash=None,
                    synthetic=True,
                ),
                workspace_id=workspace_id,
                permission=CollaborationPermission.CANVAS_VIEW,
                boundary=AuthorityBoundary.CLAIM,
                trace_id=uuid.uuid4(),
            )
            snapshot_id = snapshot.snapshot_id
            await session.commit()

        revoke_payload = {
            "shareIds": [share["shareId"]],
            "idempotencyKey": "canvas-share-revoke-001",
        }
        revoked = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/shares/revoke",
            json=revoke_payload,
            headers=_csrf(owner_session),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()[0]["state"] == "revoked"
        duplicate_revoke = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/shares/revoke",
            json=revoke_payload,
            headers=_csrf(owner_session),
        )
        assert duplicate_revoke.status_code == 200
        assert duplicate_revoke.json()[0]["duplicate"] is True

        async with database.sessions() as session:
            snapshot = await session.get(CollaborationAuthoritySnapshot, snapshot_id)
            assert snapshot is not None
            with pytest.raises(CollaborationNotFoundError):
                await RevocationFenceService(session).assert_current(
                    snapshot,
                    boundary=AuthorityBoundary.PUBLICATION,
                )

        expired_request = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers",
            json={
                "transferKind": "resource",
                "recipientMembershipId": recipient_membership["membershipId"],
                "resourceKind": "canvas",
                "resourceId": str(canvas_id),
                "idempotencyKey": "expired-canvas-transfer-001",
            },
            headers=_csrf(owner_session),
        )
        assert expired_request.status_code == 201, expired_request.text
        expired_transfer = cast(JsonObject, expired_request.json())
        async with database.sessions() as session:
            expired_row = await session.get(
                CollaborationOwnershipTransfer,
                uuid.UUID(cast(str, expired_transfer["transferId"])),
            )
            assert expired_row is not None
            await session.execute(
                update(CollaborationOwnershipTransfer)
                .where(
                    CollaborationOwnershipTransfer.transfer_id
                    == uuid.UUID(cast(str, expired_transfer["transferId"]))
                )
                .values(expires_at=expired_row.created_at + timedelta(microseconds=1))
            )
            await session.commit()
        expired_accept = await recipient.post(
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers/"
            f"{expired_transfer['transferId']}/accept",
            json={"idempotencyKey": "expired-canvas-accept-001"},
            headers=_csrf(recipient_session),
        )
        assert expired_accept.status_code == 404

        transfer_request = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers",
            json={
                "transferKind": "resource",
                "recipientMembershipId": recipient_membership["membershipId"],
                "resourceKind": "canvas",
                "resourceId": str(canvas_id),
                "idempotencyKey": "canvas-owner-transfer-001",
            },
            headers=_csrf(owner_session),
        )
        assert transfer_request.status_code == 201, transfer_request.text
        transfer = cast(JsonObject, transfer_request.json())
        owner_transfer_list = await owner.get(
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers"
        )
        recipient_transfer_list = await recipient.get(
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers"
        )
        assert owner_transfer_list.status_code == 200
        assert recipient_transfer_list.status_code == 200
        assert transfer["transferId"] in {
            item["transferId"] for item in recipient_transfer_list.json()
        }
        accept_path = (
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers/"
            f"{transfer['transferId']}/accept"
        )
        accepted_first, accepted_second = await asyncio.gather(
            recipient.post(
                accept_path,
                json={"idempotencyKey": "canvas-owner-accept-001"},
                headers=_csrf(recipient_session),
            ),
            recipient.post(
                accept_path,
                json={"idempotencyKey": "canvas-owner-accept-001"},
                headers=_csrf(recipient_session),
            ),
        )
        assert {accepted_first.status_code, accepted_second.status_code} <= {200, 409}
        assert 200 in {accepted_first.status_code, accepted_second.status_code}
        accepted = accepted_first if accepted_first.status_code == 200 else accepted_second
        assert accepted.json()["state"] == "accepted"
        duplicate_accept = await recipient.post(
            accept_path,
            json={"idempotencyKey": "canvas-owner-accept-001"},
            headers=_csrf(recipient_session),
        )
        assert duplicate_accept.status_code == 200
        assert duplicate_accept.json()["duplicate"] is True

        former_owner_change = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/resources/canvas/{canvas_id}/visibility",
            json={
                "visibilityPolicy": "workspace_visible",
                "idempotencyKey": "former-owner-visibility-001",
            },
            headers=_csrf(owner_session),
        )
        assert former_owner_change.status_code == 404
        current_owner_change = await recipient.post(
            f"{api_prefix}/workspaces/{workspace_id}/resources/canvas/{canvas_id}/visibility",
            json={
                "visibilityPolicy": "workspace_visible",
                "idempotencyKey": "current-owner-visibility-001",
            },
            headers=_csrf(recipient_session),
        )
        assert current_owner_change.status_code == 200, current_owner_change.text
        assert (
            current_owner_change.json()["ownerMembershipId"] == recipient_membership["membershipId"]
        )

        workspace_transfer_request = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers",
            json={
                "transferKind": "workspace",
                "recipientMembershipId": recipient_membership["membershipId"],
                "formerOwnerRole": "administrator",
                "idempotencyKey": "workspace-owner-transfer-001",
            },
            headers=_csrf(owner_session),
        )
        assert workspace_transfer_request.status_code == 201
        workspace_transfer = cast(JsonObject, workspace_transfer_request.json())
        workspace_accepted = await recipient.post(
            f"{api_prefix}/workspaces/{workspace_id}/ownership-transfers/"
            f"{workspace_transfer['transferId']}/accept",
            json={"idempotencyKey": "workspace-owner-accept-001"},
            headers=_csrf(recipient_session),
        )
        assert workspace_accepted.status_code == 200, workspace_accepted.text
        assert workspace_accepted.json()["state"] == "accepted"

    async with database.sessions() as session:
        workspace_row = await session.get(Workspace, workspace_id)
        owner_transition = await session.scalar(
            select(WorkspaceMembershipTransition)
            .where(
                WorkspaceMembershipTransition.membership_id
                == uuid.UUID(cast(str, recipient_membership["membershipId"]))
            )
            .order_by(WorkspaceMembershipTransition.sequence.desc())
            .limit(1)
        )
        former_owner_transition = await session.scalar(
            select(WorkspaceMembershipTransition)
            .join(
                WorkspaceMembership,
                WorkspaceMembership.membership_id == WorkspaceMembershipTransition.membership_id,
            )
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == uuid.UUID(cast(str, owner_session["user"]["id"])),
            )
            .order_by(WorkspaceMembershipTransition.sequence.desc())
            .limit(1)
        )
        assert workspace_row is not None
        assert workspace_row.owner_id == uuid.UUID(cast(str, recipient_session["user"]["id"]))
        assert owner_transition is not None and owner_transition.current_role == "owner"
        assert (
            former_owner_transition is not None
            and former_owner_transition.current_role == "administrator"
        )
        assert (
            await session.scalar(select(func.count()).select_from(CollaborationResourceShare)) == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(CollaborationResourceShareTransition)
            )
            == 2
        )
