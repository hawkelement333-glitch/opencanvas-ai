from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from opencanvas_api.db.models import (
    CollaborationAuditEvent,
    CollaborationComment,
    CollaborationCommentRevision,
    CollaborationCommentThread,
    CollaborationCommentTransition,
    CollaborationRequestIdentity,
    CollaborationResource,
    CollaborationResourceOwnershipTransition,
    DomainEventOutbox,
    DomainEventRecord,
    TraceEvent,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.domain_events import DomainEventOutboxService, DomainEventService
from tests.test_collaboration_api import _csrf, _enable_real_auth, _sign_up, _workspace

JsonObject = dict[str, Any]


async def _invite_member(
    owner: httpx.AsyncClient,
    member: httpx.AsyncClient,
    *,
    prefix: str,
    workspace_id: str,
    owner_session: JsonObject,
    member_session: JsonObject,
    role: str,
    key: str,
) -> JsonObject:
    invitation = await owner.post(
        f"{prefix}/workspaces/{workspace_id}/invitations",
        json={
            "recipientEmail": member_session["user"]["email"],
            "intendedRole": role,
            "idempotencyKey": f"comment-{key}-invite-001",
        },
        headers=_csrf(owner_session),
    )
    assert invitation.status_code == 201, invitation.text
    row = cast(JsonObject, invitation.json())
    accepted = await member.post(
        f"{prefix}/collaboration-invitations/{row['invitationId']}/accept",
        json={
            "token": row["developmentToken"],
            "idempotencyKey": f"comment-{key}-accept-001",
        },
        headers=_csrf(member_session),
    )
    assert accepted.status_code == 200, accepted.text
    return cast(JsonObject, accepted.json())


async def _register_canvas(
    database: Database,
    *,
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> None:
    async with database.sessions() as session:
        authority = await session.get(WorkspaceAuthorityVersion, workspace_id)
        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == owner_user_id,
            )
        )
        assert authority is not None and membership is not None
        now = datetime.now(UTC)
        session.add(
            CollaborationResource(
                resource_id=canvas_id,
                workspace_id=workspace_id,
                resource_kind="canvas",
                canvas_id=canvas_id,
                creator_user_id=owner_user_id,
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
                visibility_policy="workspace_visible",
                authority_generation=authority.authority_generation,
                actor_user_id=owner_user_id,
                actor_membership_id=membership.membership_id,
                reason_code="resource_registered",
                trace_id=uuid.uuid4(),
                recorded_at=now,
            )
        )
        await session.commit()


@pytest.mark.security
async def test_comments_are_bounded_idempotent_traceable_and_tombstoned(
    app: FastAPI,
    database: Database,
    api_prefix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as owner,
        httpx.AsyncClient(transport=transport, base_url="http://test") as editor,
        httpx.AsyncClient(transport=transport, base_url="http://test") as viewer,
    ):
        owner_session = await _sign_up(
            owner,
            api_prefix,
            email="comment-owner@example.test",
            display_name="Comment owner",
        )
        editor_session = await _sign_up(
            editor,
            api_prefix,
            email="comment-editor@example.test",
            display_name="Comment editor",
        )
        viewer_session = await _sign_up(
            viewer,
            api_prefix,
            email="comment-viewer@example.test",
            display_name="Comment viewer",
        )
        workspace = await _workspace(owner, api_prefix)
        editor_workspace = await _workspace(editor, api_prefix)
        editor_membership = await _invite_member(
            owner,
            editor,
            prefix=api_prefix,
            workspace_id=cast(str, workspace["id"]),
            owner_session=owner_session,
            member_session=editor_session,
            role="editor",
            key="editor",
        )
        await _invite_member(
            owner,
            viewer,
            prefix=api_prefix,
            workspace_id=cast(str, workspace["id"]),
            owner_session=owner_session,
            member_session=viewer_session,
            role="viewer",
            key="viewer",
        )
        canvas_response = await owner.post(
            f"{api_prefix}/canvases",
            json={
                "idempotencyKey": str(uuid.uuid4()),
                "name": "Comment canvas",
                "workspaceId": workspace["id"],
            },
            headers=_csrf(owner_session),
        )
        assert canvas_response.status_code == 201, canvas_response.text
        canvas = cast(JsonObject, canvas_response.json())
        workspace_id = uuid.UUID(cast(str, workspace["id"]))
        canvas_id = uuid.UUID(cast(str, canvas["id"]))
        await _register_canvas(
            database,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            owner_user_id=uuid.UUID(cast(str, owner_session["user"]["id"])),
        )
        comments_url = (
            f"{api_prefix}/workspaces/{workspace_id}/resources/canvas/{canvas_id}/comments"
        )

        for index, unsafe in enumerate(
            (
                "   ",
                "<script>alert(1)</script>",
                "[unsafe](https://example.test)",
                "**raw markdown**",
                "http://example.test",
                "x" * 5_001,
            )
        ):
            rejected = await editor.post(
                comments_url,
                json={
                    "content": unsafe,
                    "idempotencyKey": f"unsafe-comment-{index:03d}",
                },
                headers=_csrf(editor_session),
            )
            assert rejected.status_code in {400, 422}, rejected.text

        create_payload = {
            "content": "Grounded review at https://example.test/evidence",
            "idempotencyKey": "comment-create-root-001",
        }
        created = await editor.post(
            comments_url,
            json=create_payload,
            headers=_csrf(editor_session),
        )
        assert created.status_code == 201, created.text
        root = cast(JsonObject, created.json())
        assert root["depth"] == 0
        assert root["threadState"] == "open"
        assert root["state"] == "active"
        assert root["content"] == create_payload["content"]
        replay = await editor.post(
            comments_url,
            json=create_payload,
            headers=_csrf(editor_session),
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["commentId"] == root["commentId"]
        assert replay.json()["duplicate"] is True

        concurrent_payload = {
            "content": "Concurrent delivery creates one comment",
            "idempotencyKey": "comment-create-concurrent-001",
        }
        concurrent_results = await asyncio.gather(
            editor.post(
                comments_url,
                json=concurrent_payload,
                headers=_csrf(editor_session),
            ),
            editor.post(
                comments_url,
                json=concurrent_payload,
                headers=_csrf(editor_session),
            ),
        )
        assert {response.status_code for response in concurrent_results} <= {201, 409}
        assert any(response.status_code == 201 for response in concurrent_results)
        concurrent_replay = await editor.post(
            comments_url,
            json=concurrent_payload,
            headers=_csrf(editor_session),
        )
        assert concurrent_replay.status_code == 201, concurrent_replay.text
        assert concurrent_replay.json()["duplicate"] is True
        concurrent_comment = cast(JsonObject, concurrent_replay.json())
        concurrent_edits = await asyncio.gather(
            editor.post(
                f"{api_prefix}/workspaces/{workspace_id}/comments/"
                f"{concurrent_comment['commentId']}/revisions",
                json={
                    "expectedRevisionId": concurrent_comment["revisionId"],
                    "content": "Concurrent edit A",
                    "idempotencyKey": "comment-concurrent-edit-a",
                },
                headers=_csrf(editor_session),
            ),
            editor.post(
                f"{api_prefix}/workspaces/{workspace_id}/comments/"
                f"{concurrent_comment['commentId']}/revisions",
                json={
                    "expectedRevisionId": concurrent_comment["revisionId"],
                    "content": "Concurrent edit B",
                    "idempotencyKey": "comment-concurrent-edit-b",
                },
                headers=_csrf(editor_session),
            ),
        )
        assert sorted(response.status_code for response in concurrent_edits) == [201, 409]

        parent_id = cast(str, root["commentId"])
        for depth in range(1, 5):
            reply = await editor.post(
                comments_url,
                json={
                    "content": f"Bounded reply {depth}",
                    "parentCommentId": parent_id,
                    "idempotencyKey": f"comment-reply-{depth:03d}",
                },
                headers=_csrf(editor_session),
            )
            assert reply.status_code == 201, reply.text
            reply_row = cast(JsonObject, reply.json())
            assert reply_row["depth"] == depth
            assert reply_row["threadId"] == root["threadId"]
            parent_id = cast(str, reply_row["commentId"])
        too_deep = await editor.post(
            comments_url,
            json={
                "content": "Depth five is forbidden",
                "parentCommentId": parent_id,
                "idempotencyKey": "comment-reply-depth-five",
            },
            headers=_csrf(editor_session),
        )
        assert too_deep.status_code == 404

        revise_payload = {
            "expectedRevisionId": root["revisionId"],
            "content": "Corrected grounded review",
            "idempotencyKey": "comment-revise-root-001",
        }
        revised = await editor.post(
            f"{api_prefix}/workspaces/{workspace_id}/comments/{root['commentId']}/revisions",
            json=revise_payload,
            headers=_csrf(editor_session),
        )
        assert revised.status_code == 201, revised.text
        revised_row = cast(JsonObject, revised.json())
        assert revised_row["sequence"] == 2
        revise_replay = await editor.post(
            f"{api_prefix}/workspaces/{workspace_id}/comments/{root['commentId']}/revisions",
            json=revise_payload,
            headers=_csrf(editor_session),
        )
        assert revise_replay.status_code == 201
        assert revise_replay.json()["revisionId"] == revised_row["revisionId"]
        assert revise_replay.json()["duplicate"] is True
        stale = await editor.post(
            f"{api_prefix}/workspaces/{workspace_id}/comments/{root['commentId']}/revisions",
            json={
                "expectedRevisionId": root["revisionId"],
                "content": "Stale edit",
                "idempotencyKey": "comment-revise-stale-001",
            },
            headers=_csrf(editor_session),
        )
        assert stale.status_code == 409

        resolved = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/comment-threads/{root['threadId']}/resolve",
            json={
                "targetState": "resolved",
                "idempotencyKey": "comment-thread-resolve-001",
            },
            headers=_csrf(owner_session),
        )
        assert resolved.status_code == 200, resolved.text
        blocked_reply = await editor.post(
            comments_url,
            json={
                "content": "Resolved thread reply",
                "parentCommentId": root["commentId"],
                "idempotencyKey": "comment-reply-resolved-001",
            },
            headers=_csrf(editor_session),
        )
        assert blocked_reply.status_code == 404
        reopened = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/comment-threads/{root['threadId']}/resolve",
            json={
                "targetState": "reopened",
                "idempotencyKey": "comment-thread-reopen-001",
            },
            headers=_csrf(owner_session),
        )
        assert reopened.status_code == 200, reopened.text

        tombstoned = await editor.post(
            f"{api_prefix}/workspaces/{workspace_id}/comments/{root['commentId']}/moderate",
            json={
                "tombstoneKind": "remove_by_author",
                "reasonCode": "author_removed",
                "idempotencyKey": "comment-remove-root-001",
            },
            headers=_csrf(editor_session),
        )
        assert tombstoned.status_code == 200, tombstoned.text
        assert tombstoned.json()["state"] == "removed_by_author"
        assert tombstoned.json()["content"] is None
        tombstone_replay = await editor.post(
            f"{api_prefix}/workspaces/{workspace_id}/comments/{root['commentId']}/moderate",
            json={
                "tombstoneKind": "remove_by_author",
                "reasonCode": "author_removed",
                "idempotencyKey": "comment-remove-root-001",
            },
            headers=_csrf(editor_session),
        )
        assert tombstone_replay.status_code == 200
        assert tombstone_replay.json()["duplicate"] is True

        viewer_list = await viewer.get(comments_url)
        assert viewer_list.status_code == 200, viewer_list.text
        root_for_viewer = next(
            row for row in viewer_list.json() if row["commentId"] == root["commentId"]
        )
        assert root_for_viewer["content"] is None
        viewer_create = await viewer.post(
            comments_url,
            json={
                "content": "Visibility is not comment authority",
                "idempotencyKey": "viewer-comment-denied-001",
            },
            headers=_csrf(viewer_session),
        )
        assert viewer_create.status_code == 404
        viewer_history = await viewer.get(
            f"{api_prefix}/workspaces/{workspace_id}/comments/{root['commentId']}/revisions"
        )
        assert viewer_history.status_code == 404

        moderated = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/comments/"
            f"{concurrent_comment['commentId']}/moderate",
            json={
                "tombstoneKind": "hide_by_moderation",
                "reasonCode": "moderation_policy",
                "idempotencyKey": "comment-moderate-concurrent-001",
            },
            headers=_csrf(owner_session),
        )
        assert moderated.status_code == 200, moderated.text
        assert moderated.json()["state"] == "hidden_by_moderation"
        assert moderated.json()["content"] is None
        moderator_history = await owner.get(
            f"{api_prefix}/workspaces/{workspace_id}/comments/"
            f"{concurrent_comment['commentId']}/revisions"
        )
        assert moderator_history.status_code == 200
        leaked_history = await viewer.get(
            f"{api_prefix}/workspaces/{workspace_id}/comments/"
            f"{concurrent_comment['commentId']}/revisions"
        )
        assert leaked_history.status_code == 404

        cross_scope = await editor.get(
            f"{api_prefix}/workspaces/{editor_workspace['id']}/comments/"
            f"{root['commentId']}/revisions"
        )
        assert cross_scope.status_code == 404
        history = await editor.get(
            f"{api_prefix}/workspaces/{workspace_id}/comments/{root['commentId']}/revisions"
        )
        assert history.status_code == 200, history.text
        assert [row["content"] for row in history.json()] == [
            create_payload["content"],
            revise_payload["content"],
        ]
        removed = await owner.post(
            f"{api_prefix}/workspaces/{workspace_id}/memberships/"
            f"{editor_membership['membershipId']}/remove",
            json={"idempotencyKey": "comment-editor-remove-001"},
            headers=_csrf(owner_session),
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["state"] == "removed"
        assert (await editor.get(comments_url)).status_code == 404
        revoked_revision = await editor.post(
            f"{api_prefix}/workspaces/{workspace_id}/comments/"
            f"{concurrent_comment['commentId']}/revisions",
            json={
                "expectedRevisionId": concurrent_comment["revisionId"],
                "content": "Revoked authority cannot edit",
                "idempotencyKey": "comment-revoked-edit-001",
            },
            headers=_csrf(editor_session),
        )
        assert revoked_revision.status_code in {404, 409}

    async with database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationComment)
                .where(CollaborationComment.thread_id == uuid.UUID(cast(str, root["threadId"])))
            )
            == 5
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationCommentRevision)
                .where(
                    CollaborationCommentRevision.comment_id
                    == uuid.UUID(cast(str, root["commentId"]))
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationCommentTransition)
                .where(
                    CollaborationCommentTransition.comment_id
                    == uuid.UUID(cast(str, root["commentId"]))
                )
            )
            == 3
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationCommentThread)
                .where(
                    CollaborationCommentThread.thread_id == uuid.UUID(cast(str, root["threadId"]))
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DomainEventRecord)
                .where(
                    DomainEventRecord.workspace_id == workspace_id,
                    DomainEventRecord.event_type.like("comment.%"),
                )
            )
            == 12
        )
        outbox = DomainEventOutboxService(session)
        while await outbox.process_one(owner_id="comment-activity-projector"):
            await session.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as owner_again:
        signed_in = await owner_again.post(
            f"{api_prefix}/auth/signin",
            json={
                "email": "comment-owner@example.test",
                "password": "Correct-Horse-2026",
            },
        )
        assert signed_in.status_code == 200, signed_in.text
        activity = await owner_again.get(
            f"{api_prefix}/workspaces/{workspace_id}/collaboration-activity",
            params={"resourceKind": "canvas", "resourceId": str(canvas_id)},
        )
        assert activity.status_code == 200, activity.text
        rows = cast(list[JsonObject], activity.json())
        assert {row["eventType"] for row in rows} >= {
            "comment.created",
            "comment.reply.created",
            "comment.revised",
            "comment.tombstoned",
            "comment.thread.resolved",
            "comment.thread.reopened",
        }
        assert all("content" not in row for row in rows)
        assert len({row["eventId"] for row in rows}) == len(rows)
        filtered = await owner_again.get(
            f"{api_prefix}/workspaces/{workspace_id}/collaboration-activity",
            params={
                "resourceKind": "canvas",
                "resourceId": str(canvas_id),
                "eventType": "comment.created",
            },
        )
        assert filtered.status_code == 200, filtered.text
        assert len(filtered.json()) == 2
        assert root["commentId"] in {row["commentId"] for row in filtered.json()}
        first_page = await owner_again.get(
            f"{api_prefix}/workspaces/{workspace_id}/collaboration-activity",
            params={
                "resourceKind": "canvas",
                "resourceId": str(canvas_id),
                "limit": 1,
                "offset": 0,
            },
        )
        second_page = await owner_again.get(
            f"{api_prefix}/workspaces/{workspace_id}/collaboration-activity",
            params={
                "resourceKind": "canvas",
                "resourceId": str(canvas_id),
                "limit": 1,
                "offset": 1,
            },
        )
        assert first_page.status_code == second_page.status_code == 200
        assert first_page.json()[0]["eventId"] != second_page.json()[0]["eventId"]

        async def evidence_counts() -> tuple[int, ...]:
            counts: list[int] = []
            async with database.sessions() as session:
                for model in (
                    CollaborationComment,
                    CollaborationCommentRevision,
                    CollaborationRequestIdentity,
                    CollaborationAuditEvent,
                    DomainEventRecord,
                    DomainEventOutbox,
                    TraceEvent,
                ):
                    count = await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.workspace_id == workspace_id)
                    )
                    counts.append(int(count or 0))
            return tuple(counts)

        evidence_before = await evidence_counts()

        async def fail_event(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("injected event failure")

        with monkeypatch.context() as patch:
            patch.setattr(DomainEventService, "record", fail_event)
            with pytest.raises(RuntimeError, match="injected event failure"):
                await owner_again.post(
                    comments_url,
                    json={
                        "content": "This transaction must roll back",
                        "idempotencyKey": "comment-failure-rollback-001",
                    },
                    headers={
                        "X-CSRF-Token": signed_in.json()["csrfToken"],
                    },
                )

        evidence_after = await evidence_counts()
        assert evidence_after == evidence_before
