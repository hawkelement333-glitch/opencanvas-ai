from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import (
    CollaborationComment,
    CollaborationCommentRevision,
    CollaborationCommentThread,
    CollaborationCommentThreadTransition,
    CollaborationCommentTransition,
    DomainActivityEntry,
    DomainEventOutbox,
    DomainEventRecord,
    Workspace,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration import (
    COLLABORATION_POLICY_VERSION,
    CollaborationConflictError,
    CollaborationNotFoundError,
    CollaborationValidationError,
)
from opencanvas_api.services.collaboration_authority import (
    CollaborationAction,
    CollaborationAuthorizationService,
    CollaborationPermission,
)
from opencanvas_api.services.collaboration_management import (
    _audit,
    _request_identity,
    _request_replay,
    _validate_idempotency_key,
)
from opencanvas_api.services.collaboration_resources import (
    AuthorityBoundary,
    ResourceAccessDecision,
    RevocationFenceService,
    ShareAccessLevel,
    ShareResourceKind,
    SharingService,
)
from opencanvas_api.services.domain_events import (
    CreateDomainEvent,
    DomainEventService,
)
from opencanvas_api.services.trace import CompleteTraceInput, StartTraceInput, TraceService

COMMENT_MAX_LENGTH = 5_000
COMMENT_MAX_DEPTH = 4
COMMENTS_PER_THREAD_MAX = 500
COMMENT_CREATION_RATE_PER_MINUTE = 30
COMMENT_PAGE_DEFAULT = 50
COMMENT_PAGE_MAX = 100
ACTIVITY_PAGE_DEFAULT = 50
ACTIVITY_PAGE_MAX = 100

_UNSAFE_CONTENT = re.compile(
    r"<\s*/?\s*[a-z][^>]*>|"
    r"\[[^\]]+\]\s*\([^)]+\)|"
    r"(?:javascript|data|vbscript|file)\s*:|"
    r"http://|"
    r"!\[[^\]]*\]\s*\([^)]+\)|"
    r"`|"
    r"\*\*|__|"
    r"^[ \t]*(?:#{1,6}[ \t]|>[ \t]|[-+*][ \t]|\d+\.[ \t])",
    flags=re.IGNORECASE | re.MULTILINE,
)
_CONTROL_CONTENT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class CommentState(StrEnum):
    ACTIVE = "active"
    EDITED = "edited"
    HIDDEN_BY_MODERATION = "hidden_by_moderation"
    REMOVED_BY_AUTHOR = "removed_by_author"


class CommentRevisionKind(StrEnum):
    CREATED = "created"
    EDITED = "edited"


class CommentThreadState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    REOPENED = "reopened"


class CommentTombstoneKind(StrEnum):
    REMOVE_BY_AUTHOR = "remove_by_author"
    HIDE_BY_MODERATION = "hide_by_moderation"


class CollaborationActivityKind(StrEnum):
    COMMENT_CREATED = "comment.created"
    COMMENT_REPLY_CREATED = "comment.reply.created"
    COMMENT_REVISED = "comment.revised"
    COMMENT_TOMBSTONED = "comment.tombstoned"
    COMMENT_THREAD_RESOLVED = "comment.thread.resolved"
    COMMENT_THREAD_REOPENED = "comment.thread.reopened"
    RESOURCE_SHARE_CREATED = "resource.share.created"
    RESOURCE_SHARE_CHANGED = "resource.share.changed"
    RESOURCE_SHARE_REVOKED = "resource.share.revoked"
    RESOURCE_VISIBILITY_CHANGED = "resource.visibility.changed"
    RESOURCE_OWNERSHIP_CHANGED = "resource.ownership_changed"


@dataclass(frozen=True, slots=True)
class CommentRecord:
    thread: CollaborationCommentThread
    thread_transition: CollaborationCommentThreadTransition
    comment: CollaborationComment
    transition: CollaborationCommentTransition
    revision: CollaborationCommentRevision | None
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    comment: CollaborationComment
    transition: CollaborationCommentTransition
    revision: CollaborationCommentRevision
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ThreadRecord:
    thread: CollaborationCommentThread
    transition: CollaborationCommentThreadTransition
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class CollaborationActivityRecord:
    activity_id: uuid.UUID
    event_id: uuid.UUID
    event_type: CollaborationActivityKind
    workspace_id: uuid.UUID
    canvas_id: uuid.UUID | None
    sequence: int
    resource_kind: ShareResourceKind
    resource_id: uuid.UUID
    comment_id: uuid.UUID | None
    thread_id: uuid.UUID | None
    actor_user_id: uuid.UUID
    trace_id: uuid.UUID
    occurred_at: datetime


class CommentService:
    """Bounded plain-text comments over exact typed collaboration resources."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self.sharing = SharingService(session, now_factory=self._now_factory)
        self.authorization = CollaborationAuthorizationService(session)
        self.fences = RevocationFenceService(session, now_factory=self._now_factory)
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def list_comments(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind | str,
        resource_id: uuid.UUID,
        limit: int = COMMENT_PAGE_DEFAULT,
        offset: int = 0,
    ) -> list[CommentRecord]:
        if not 1 <= limit <= COMMENT_PAGE_MAX or not 0 <= offset <= 100_000:
            raise CollaborationValidationError()
        access = await self._resource_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
        )
        kind = ShareResourceKind(resource_kind)
        rows = (
            await self.session.scalars(
                select(CollaborationComment)
                .where(
                    CollaborationComment.workspace_id == workspace_id,
                    CollaborationComment.resource_kind == kind.value,
                    CollaborationComment.resource_id == resource_id,
                )
                .order_by(
                    CollaborationComment.created_at,
                    CollaborationComment.thread_id,
                    CollaborationComment.thread_sequence,
                    CollaborationComment.comment_id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        records: list[CommentRecord] = []
        for comment in rows:
            record = await self._record(comment)
            if record is None:
                raise CollaborationConflictError()
            records.append(record)
        await self._revalidate_access(principal, access)
        return records

    async def list_revisions(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        comment_id: uuid.UUID,
        limit: int = COMMENT_PAGE_DEFAULT,
        offset: int = 0,
    ) -> list[CollaborationCommentRevision]:
        if not 1 <= limit <= COMMENT_PAGE_MAX or not 0 <= offset <= 100_000:
            raise CollaborationValidationError()
        comment = await self._comment(comment_id, workspace_id)
        if comment is None:
            raise CollaborationNotFoundError()
        access = await self._resource_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=comment.resource_kind,
            resource_id=comment.resource_id,
        )
        transition = await self._comment_transition(comment.comment_id, workspace_id)
        if transition is None:
            raise CollaborationConflictError()
        if (
            transition.current_state
            in {
                CommentState.HIDDEN_BY_MODERATION.value,
                CommentState.REMOVED_BY_AUTHOR.value,
            }
            and principal.user_id != comment.author_user_id
        ):
            moderation = await self.authorization.evaluate(
                principal=principal,
                workspace_id=workspace_id,
                action=CollaborationAction.COMMENT_MODERATE,
                expected_authority_generation=access.authority_generation,
            )
            if not moderation.allowed:
                raise CollaborationNotFoundError()
        rows = (
            await self.session.scalars(
                select(CollaborationCommentRevision)
                .where(
                    CollaborationCommentRevision.comment_id == comment_id,
                    CollaborationCommentRevision.workspace_id == workspace_id,
                )
                .order_by(CollaborationCommentRevision.sequence)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        await self._revalidate_access(principal, access)
        return list(rows)

    async def create(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind | str,
        resource_id: uuid.UUID,
        content: str,
        idempotency_key: str,
        parent_comment_id: uuid.UUID | None = None,
    ) -> CommentRecord:
        _validate_idempotency_key(idempotency_key)
        normalized = _normalize_content(content)
        try:
            kind = ShareResourceKind(resource_kind)
        except ValueError as exc:
            raise CollaborationNotFoundError() from exc
        operation = "comment.reply" if parent_comment_id else "comment.create"
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "resourceKind": kind.value,
                "resourceId": str(resource_id),
                "parentCommentId": str(parent_comment_id) if parent_comment_id else None,
                "contentDigest": _content_digest(normalized),
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
            comment = await self._comment(replay.result_id, workspace_id)
            record = await self._record(comment) if comment is not None else None
            if record is None:
                raise CollaborationConflictError()
            return CommentRecord(
                record.thread,
                record.thread_transition,
                record.comment,
                record.transition,
                record.revision,
                duplicate=True,
            )
        access = await self._resource_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=kind,
            resource_id=resource_id,
        )
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=CollaborationAction.COMMENT_CREATE,
            expected_authority_generation=access.authority_generation,
        )
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.authority_generation is None
        ):
            raise CollaborationNotFoundError()
        now = _aware(self._now_factory())
        recent = await self.session.scalar(
            select(func.count())
            .select_from(CollaborationComment)
            .where(
                CollaborationComment.workspace_id == workspace_id,
                CollaborationComment.author_membership_id == decision.membership_id,
                CollaborationComment.created_at >= now - timedelta(minutes=1),
            )
        )
        if (recent or 0) >= COMMENT_CREATION_RATE_PER_MINUTE:
            raise CollaborationValidationError()
        parent: CollaborationComment | None = None
        thread: CollaborationCommentThread | None = None
        thread_transition: CollaborationCommentThreadTransition | None = None
        depth = 0
        if parent_comment_id is not None:
            parent = await self._comment(parent_comment_id, workspace_id)
            if (
                parent is None
                or parent.resource_kind != kind.value
                or parent.resource_id != resource_id
            ):
                raise CollaborationNotFoundError()
            parent_transition = await self._comment_transition(parent.comment_id, workspace_id)
            if (
                parent_transition is None
                or parent_transition.current_state
                in {
                    CommentState.HIDDEN_BY_MODERATION.value,
                    CommentState.REMOVED_BY_AUTHOR.value,
                }
                or parent.depth >= COMMENT_MAX_DEPTH
            ):
                raise CollaborationNotFoundError()
            thread = await self.session.get(CollaborationCommentThread, parent.thread_id)
            thread_transition = await self._thread_transition(parent.thread_id, workspace_id)
            if (
                thread is None
                or thread_transition is None
                or thread_transition.current_state == CommentThreadState.RESOLVED.value
            ):
                raise CollaborationNotFoundError()
            depth = parent.depth + 1
        request_id = uuid.uuid5(
            workspace_id,
            f"{principal.user_id}:{operation}:{idempotency_key}",
        )
        comment_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=comment_id,
                object_type="comment",
                operation="comment_reply" if parent else "comment_create",
                metadata={"resourceKind": kind.value, "replyDepth": depth},
            )
        )
        snapshot = await self.fences.capture(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.COMMENT_CREATE,
            boundary=AuthorityBoundary.SERVICE_CALL,
            trace_id=trace_id,
            resource=access.resource,
            share=access.share,
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="comment",
            subject_id=comment_id,
            action=operation,
            reason_code="comment_reply_created" if parent else "comment_created",
            trace_id=trace_id,
            metadata={
                "resourceKind": kind.value,
                "resourceId": str(resource_id),
                "replyDepth": depth,
                "contentDigest": _content_digest(normalized),
            },
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        if thread is None:
            resource = access.resource
            if resource is None:
                raise CollaborationConflictError()
            resource_sequence = (
                await self.session.scalar(
                    select(func.max(CollaborationCommentThread.resource_sequence)).where(
                        CollaborationCommentThread.workspace_id == workspace_id,
                        CollaborationCommentThread.resource_kind == kind.value,
                        CollaborationCommentThread.resource_id == resource_id,
                    )
                )
                or 0
            ) + 1
            thread = CollaborationCommentThread(
                thread_id=uuid.uuid4(),
                workspace_id=workspace_id,
                resource_id=resource_id,
                resource_kind=kind.value,
                canvas_id=resource.resource.canvas_id,
                resource_sequence=resource_sequence,
                creator_membership_id=decision.membership_id,
                creator_user_id=principal.user_id,
                authority_generation=decision.authority_generation,
                collaboration_policy_version=COLLABORATION_POLICY_VERSION,
                creation_request_id=request_id,
                creation_trace_id=trace_id,
                creation_audit_event_id=audit.audit_event_id,
                created_at=now,
            )
            self.session.add(thread)
            await self.session.flush()
            thread_transition = CollaborationCommentThreadTransition(
                transition_id=uuid.uuid4(),
                thread_id=thread.thread_id,
                workspace_id=workspace_id,
                resource_id=resource_id,
                resource_kind=kind.value,
                sequence=0,
                previous_state=None,
                current_state=CommentThreadState.OPEN.value,
                authority_generation=decision.authority_generation,
                actor_user_id=principal.user_id,
                actor_membership_id=decision.membership_id,
                reason_code="comment_thread_created",
                request_id=request_id,
                trace_id=trace_id,
                audit_event_id=audit.audit_event_id,
                recorded_at=now,
            )
            self.session.add(thread_transition)
            await self.session.flush()
        if thread_transition is None:
            raise CollaborationConflictError()
        thread_sequence = (
            await self.session.scalar(
                select(func.max(CollaborationComment.thread_sequence)).where(
                    CollaborationComment.thread_id == thread.thread_id
                )
            )
            or 0
        ) + 1
        if thread_sequence > COMMENTS_PER_THREAD_MAX:
            raise CollaborationValidationError()
        comment = CollaborationComment(
            comment_id=comment_id,
            thread_id=thread.thread_id,
            workspace_id=workspace_id,
            resource_id=resource_id,
            resource_kind=kind.value,
            parent_comment_id=parent.comment_id if parent else None,
            depth=depth,
            thread_sequence=thread_sequence,
            author_membership_id=decision.membership_id,
            author_user_id=principal.user_id,
            authority_generation=decision.authority_generation,
            collaboration_policy_version=COLLABORATION_POLICY_VERSION,
            creation_request_id=request_id,
            creation_trace_id=trace_id,
            creation_audit_event_id=audit.audit_event_id,
            created_at=now,
        )
        revision = CollaborationCommentRevision(
            revision_id=uuid.uuid4(),
            comment_id=comment_id,
            thread_id=thread.thread_id,
            workspace_id=workspace_id,
            resource_id=resource_id,
            resource_kind=kind.value,
            sequence=1,
            previous_revision_id=None,
            revision_kind=CommentRevisionKind.CREATED.value,
            author_membership_id=decision.membership_id,
            author_user_id=principal.user_id,
            content=normalized,
            content_digest=_content_digest(normalized),
            authority_generation=decision.authority_generation,
            request_id=request_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            created_at=now,
        )
        transition = CollaborationCommentTransition(
            transition_id=uuid.uuid4(),
            comment_id=comment_id,
            thread_id=thread.thread_id,
            workspace_id=workspace_id,
            resource_id=resource_id,
            resource_kind=kind.value,
            sequence=0,
            previous_state=None,
            current_state=CommentState.ACTIVE.value,
            visible_revision_id=revision.revision_id,
            authority_generation=decision.authority_generation,
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            reason_code="comment_reply_created" if parent else "comment_created",
            request_id=request_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add_all((comment, revision, transition))
        await self.session.flush()
        self.session.add(
            _request_identity(
                actor_user_id=principal.user_id,
                workspace_id=workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_kind="comment",
                result_id=comment_id,
                trace_id=trace_id,
                now=now,
            )
        )
        await self._event(
            event_type="comment.reply.created" if parent else "comment.created",
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=thread.canvas_id,
            subject_id=comment_id,
            related_id=thread.thread_id,
            source=f"comment:{comment_id}:transition:0",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            payload={
                "resourceKind": kind.value,
                "state": CommentState.ACTIVE.value,
                "revisionSequence": 1,
                "replyDepth": depth,
            },
        )
        await self.fences.assert_current(snapshot, boundary=AuthorityBoundary.PUBLICATION)
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=comment_id,
                object_type="comment",
                operation="comment_reply" if parent else "comment_create",
                metadata={"resourceKind": kind.value, "replyDepth": depth},
            )
        )
        return CommentRecord(
            thread,
            thread_transition,
            comment,
            transition,
            revision,
        )

    async def revise(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        comment_id: uuid.UUID,
        expected_revision_id: uuid.UUID,
        content: str,
        idempotency_key: str,
    ) -> RevisionRecord:
        _validate_idempotency_key(idempotency_key)
        normalized = _normalize_content(content)
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "commentId": str(comment_id),
                "expectedRevisionId": str(expected_revision_id),
                "contentDigest": _content_digest(normalized),
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="comment.revise",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            revision = await self.session.get(CollaborationCommentRevision, replay.result_id)
            comment = await self._comment(comment_id, workspace_id)
            transition = await self._comment_transition(comment_id, workspace_id)
            if revision is None or comment is None or transition is None:
                raise CollaborationConflictError()
            return RevisionRecord(comment, transition, revision, duplicate=True)
        comment = await self._comment(comment_id, workspace_id)
        if comment is None or comment.author_user_id != principal.user_id:
            raise CollaborationNotFoundError()
        access = await self._resource_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=comment.resource_kind,
            resource_id=comment.resource_id,
        )
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=CollaborationAction.COMMENT_REVISE,
            expected_authority_generation=access.authority_generation,
        )
        current = await self._comment_transition(comment_id, workspace_id)
        previous = await self._revision(expected_revision_id, comment_id, workspace_id)
        if (
            not decision.allowed
            or decision.membership_id != comment.author_membership_id
            or decision.authority_generation is None
            or current is None
            or current.current_state
            in {
                CommentState.HIDDEN_BY_MODERATION.value,
                CommentState.REMOVED_BY_AUTHOR.value,
            }
            or current.visible_revision_id != expected_revision_id
            or previous is None
        ):
            raise CollaborationConflictError()
        now = _aware(self._now_factory())
        revision_id = uuid.uuid4()
        request_id = uuid.uuid5(
            workspace_id,
            f"{principal.user_id}:comment.revise:{idempotency_key}",
        )
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=comment_id,
                object_type="comment",
                operation="comment_revise",
                metadata={"revisionSequence": previous.sequence + 1},
            )
        )
        snapshot = await self.fences.capture(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.COMMENT_EDIT_OWN,
            boundary=AuthorityBoundary.SERVICE_CALL,
            trace_id=trace_id,
            resource=access.resource,
            share=access.share,
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="comment_revision",
            subject_id=revision_id,
            action="comment.revise",
            reason_code="comment_edited",
            trace_id=trace_id,
            metadata={
                "commentId": str(comment_id),
                "revisionSequence": previous.sequence + 1,
                "contentDigest": _content_digest(normalized),
            },
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        revision = CollaborationCommentRevision(
            revision_id=revision_id,
            comment_id=comment.comment_id,
            thread_id=comment.thread_id,
            workspace_id=workspace_id,
            resource_id=comment.resource_id,
            resource_kind=comment.resource_kind,
            sequence=previous.sequence + 1,
            previous_revision_id=previous.revision_id,
            revision_kind=CommentRevisionKind.EDITED.value,
            author_membership_id=decision.membership_id,
            author_user_id=principal.user_id,
            content=normalized,
            content_digest=_content_digest(normalized),
            authority_generation=decision.authority_generation,
            request_id=request_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            created_at=now,
        )
        transition = CollaborationCommentTransition(
            transition_id=uuid.uuid4(),
            comment_id=comment.comment_id,
            thread_id=comment.thread_id,
            workspace_id=workspace_id,
            resource_id=comment.resource_id,
            resource_kind=comment.resource_kind,
            sequence=current.sequence + 1,
            previous_state=current.current_state,
            current_state=CommentState.EDITED.value,
            visible_revision_id=revision_id,
            authority_generation=decision.authority_generation,
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            reason_code="comment_edited",
            request_id=request_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add_all((revision, transition))
        self.session.add(
            _request_identity(
                actor_user_id=principal.user_id,
                workspace_id=workspace_id,
                operation="comment.revise",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_kind="comment_revision",
                result_id=revision_id,
                trace_id=trace_id,
                now=now,
            )
        )
        await self.session.flush()
        thread = await self.session.get(CollaborationCommentThread, comment.thread_id)
        if thread is None:
            raise CollaborationConflictError()
        await self._event(
            event_type="comment.revised",
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=thread.canvas_id,
            subject_id=comment_id,
            related_id=thread.thread_id,
            source=f"comment:{comment_id}:transition:{transition.sequence}",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            payload={
                "resourceKind": comment.resource_kind,
                "state": CommentState.EDITED.value,
                "revisionSequence": revision.sequence,
                "replyDepth": comment.depth,
            },
        )
        await self.fences.assert_current(snapshot, boundary=AuthorityBoundary.PUBLICATION)
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=comment_id,
                object_type="comment",
                operation="comment_revise",
                metadata={"revisionSequence": revision.sequence},
            )
        )
        return RevisionRecord(comment, transition, revision)

    async def tombstone(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        comment_id: uuid.UUID,
        tombstone_kind: CommentTombstoneKind | str,
        reason_code: str,
        idempotency_key: str,
    ) -> CommentRecord:
        _validate_idempotency_key(idempotency_key)
        try:
            kind = CommentTombstoneKind(tombstone_kind)
        except ValueError as exc:
            raise CollaborationValidationError() from exc
        safe_reason = _reason_code(reason_code)
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "commentId": str(comment_id),
                "tombstoneKind": kind.value,
                "reasonCode": safe_reason,
            }
        )
        replay = await _request_replay(
            self.session,
            actor_user_id=principal.user_id,
            workspace_id=workspace_id,
            operation="comment.tombstone",
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            comment = await self._comment(comment_id, workspace_id)
            record = await self._record(comment) if comment else None
            if record is None:
                raise CollaborationConflictError()
            return CommentRecord(
                record.thread,
                record.thread_transition,
                record.comment,
                record.transition,
                record.revision,
                duplicate=True,
            )
        comment = await self._comment(comment_id, workspace_id)
        if comment is None:
            raise CollaborationNotFoundError()
        access = await self._resource_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=comment.resource_kind,
            resource_id=comment.resource_id,
        )
        action = (
            CollaborationAction.COMMENT_TOMBSTONE
            if kind is CommentTombstoneKind.REMOVE_BY_AUTHOR
            else CollaborationAction.COMMENT_MODERATE
        )
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=action,
            expected_authority_generation=access.authority_generation,
        )
        current = await self._comment_transition(comment_id, workspace_id)
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.authority_generation is None
            or current is None
            or current.current_state
            in {
                CommentState.HIDDEN_BY_MODERATION.value,
                CommentState.REMOVED_BY_AUTHOR.value,
            }
            or (
                kind is CommentTombstoneKind.REMOVE_BY_AUTHOR
                and (
                    principal.user_id != comment.author_user_id
                    or decision.membership_id != comment.author_membership_id
                )
            )
        ):
            raise CollaborationNotFoundError()
        state = (
            CommentState.REMOVED_BY_AUTHOR
            if kind is CommentTombstoneKind.REMOVE_BY_AUTHOR
            else CommentState.HIDDEN_BY_MODERATION
        )
        now = _aware(self._now_factory())
        request_id = uuid.uuid5(
            workspace_id,
            f"{principal.user_id}:comment.tombstone:{idempotency_key}",
        )
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=comment_id,
                object_type="comment",
                operation="comment_tombstone",
                metadata={"state": state.value, "reasonCode": safe_reason},
            )
        )
        snapshot = await self.fences.capture(
            principal=principal,
            workspace_id=workspace_id,
            permission=(
                CollaborationPermission.COMMENT_EDIT_OWN
                if kind is CommentTombstoneKind.REMOVE_BY_AUTHOR
                else CollaborationPermission.COMMENT_MODERATE
            ),
            boundary=AuthorityBoundary.SERVICE_CALL,
            trace_id=trace_id,
            resource=access.resource,
            share=access.share,
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="comment_transition",
            subject_id=comment_id,
            action="comment.tombstone",
            reason_code=safe_reason,
            trace_id=trace_id,
            metadata={"commentId": str(comment_id), "state": state.value},
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        transition = CollaborationCommentTransition(
            transition_id=uuid.uuid4(),
            comment_id=comment.comment_id,
            thread_id=comment.thread_id,
            workspace_id=workspace_id,
            resource_id=comment.resource_id,
            resource_kind=comment.resource_kind,
            sequence=current.sequence + 1,
            previous_state=current.current_state,
            current_state=state.value,
            visible_revision_id=None,
            authority_generation=decision.authority_generation,
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            reason_code=safe_reason,
            request_id=request_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add(transition)
        self.session.add(
            _request_identity(
                actor_user_id=principal.user_id,
                workspace_id=workspace_id,
                operation="comment.tombstone",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_kind="comment_transition",
                result_id=transition.transition_id,
                trace_id=trace_id,
                now=now,
            )
        )
        await self.session.flush()
        thread = await self.session.get(CollaborationCommentThread, comment.thread_id)
        thread_transition = await self._thread_transition(comment.thread_id, workspace_id)
        if thread is None or thread_transition is None:
            raise CollaborationConflictError()
        await self._event(
            event_type="comment.tombstoned",
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=thread.canvas_id,
            subject_id=comment_id,
            related_id=thread.thread_id,
            source=f"comment:{comment_id}:transition:{transition.sequence}",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            payload={
                "resourceKind": comment.resource_kind,
                "state": state.value,
                "replyDepth": comment.depth,
                "reasonCode": safe_reason,
            },
        )
        await self.fences.assert_current(snapshot, boundary=AuthorityBoundary.PUBLICATION)
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=comment_id,
                object_type="comment",
                operation="comment_tombstone",
                metadata={"state": state.value, "reasonCode": safe_reason},
            )
        )
        return CommentRecord(
            thread,
            thread_transition,
            comment,
            transition,
            None,
        )

    async def set_thread_state(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        thread_id: uuid.UUID,
        target_state: CommentThreadState | str,
        idempotency_key: str,
    ) -> ThreadRecord:
        _validate_idempotency_key(idempotency_key)
        try:
            target = CommentThreadState(target_state)
        except ValueError as exc:
            raise CollaborationValidationError() from exc
        if target not in {CommentThreadState.RESOLVED, CommentThreadState.REOPENED}:
            raise CollaborationValidationError()
        operation = (
            "comment.thread.resolve"
            if target is CommentThreadState.RESOLVED
            else "comment.thread.reopen"
        )
        request_digest = _digest(
            {
                "workspaceId": str(workspace_id),
                "threadId": str(thread_id),
                "targetState": target.value,
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
            thread = await self.session.get(CollaborationCommentThread, thread_id)
            transition = await self._thread_transition(thread_id, workspace_id)
            if thread is None or transition is None:
                raise CollaborationConflictError()
            return ThreadRecord(thread, transition, duplicate=True)
        thread = await self.session.scalar(
            select(CollaborationCommentThread).where(
                CollaborationCommentThread.thread_id == thread_id,
                CollaborationCommentThread.workspace_id == workspace_id,
            )
        )
        if thread is None:
            raise CollaborationNotFoundError()
        access = await self._resource_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=thread.resource_kind,
            resource_id=thread.resource_id,
        )
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=CollaborationAction.COMMENT_THREAD_RESOLVE,
            expected_authority_generation=access.authority_generation,
        )
        current = await self._thread_transition(thread_id, workspace_id)
        if (
            not decision.allowed
            or decision.membership_id is None
            or decision.authority_generation is None
            or current is None
            or (
                target is CommentThreadState.RESOLVED
                and current.current_state
                not in {CommentThreadState.OPEN.value, CommentThreadState.REOPENED.value}
            )
            or (
                target is CommentThreadState.REOPENED
                and current.current_state != CommentThreadState.RESOLVED.value
            )
        ):
            raise CollaborationConflictError()
        now = _aware(self._now_factory())
        request_id = uuid.uuid5(workspace_id, f"{principal.user_id}:{operation}:{idempotency_key}")
        trace_id = uuid.uuid4()
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment_thread",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=thread_id,
                object_type="comment_thread",
                operation=operation.replace(".", "_"),
                metadata={"state": target.value},
            )
        )
        snapshot = await self.fences.capture(
            principal=principal,
            workspace_id=workspace_id,
            permission=CollaborationPermission.COMMENT_RESOLVE,
            boundary=AuthorityBoundary.SERVICE_CALL,
            trace_id=trace_id,
            resource=access.resource,
            share=access.share,
        )
        audit = _audit(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            subject_kind="comment_thread",
            subject_id=thread_id,
            action=operation,
            reason_code=(
                "comment_thread_resolved"
                if target is CommentThreadState.RESOLVED
                else "comment_thread_reopened"
            ),
            trace_id=trace_id,
            metadata={"threadId": str(thread_id), "state": target.value},
            now=now,
        )
        self.session.add(audit)
        await self.session.flush()
        transition = CollaborationCommentThreadTransition(
            transition_id=uuid.uuid4(),
            thread_id=thread_id,
            workspace_id=workspace_id,
            resource_id=thread.resource_id,
            resource_kind=thread.resource_kind,
            sequence=current.sequence + 1,
            previous_state=current.current_state,
            current_state=target.value,
            authority_generation=decision.authority_generation,
            actor_user_id=principal.user_id,
            actor_membership_id=decision.membership_id,
            reason_code=audit.reason_code,
            request_id=request_id,
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            recorded_at=now,
        )
        self.session.add(transition)
        self.session.add(
            _request_identity(
                actor_user_id=principal.user_id,
                workspace_id=workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_kind="comment_thread_transition",
                result_id=transition.transition_id,
                trace_id=trace_id,
                now=now,
            )
        )
        await self.session.flush()
        await self._event(
            event_type=(
                "comment.thread.resolved"
                if target is CommentThreadState.RESOLVED
                else "comment.thread.reopened"
            ),
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=thread.canvas_id,
            subject_id=thread_id,
            related_id=thread.resource_id,
            source=f"comment-thread:{thread_id}:transition:{transition.sequence}",
            trace_id=trace_id,
            audit_event_id=audit.audit_event_id,
            payload={"resourceKind": thread.resource_kind, "state": target.value},
        )
        await self.fences.assert_current(snapshot, boundary=AuthorityBoundary.PUBLICATION)
        await self.trace.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                event_type="collaboration.comment_thread",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=thread_id,
                object_type="comment_thread",
                operation=operation.replace(".", "_"),
                metadata={"state": target.value},
            )
        )
        return ThreadRecord(thread, transition)

    async def _resource_access(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind | str,
        resource_id: uuid.UUID,
    ) -> ResourceAccessDecision:
        access = await self.sharing.evaluate_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            access_level=ShareAccessLevel.VIEW,
        )
        if (
            not access.allowed
            or access.resource is None
            or access.membership_id is None
            or access.authority_generation is None
        ):
            raise CollaborationNotFoundError()
        return access

    async def _revalidate_access(
        self,
        principal: Principal,
        access: ResourceAccessDecision,
    ) -> None:
        if access.resource is None or access.authority_generation is None:
            raise CollaborationNotFoundError()
        current = await self.sharing.evaluate_access(
            principal=principal,
            workspace_id=access.resource.resource.workspace_id,
            resource_kind=access.resource.resource.resource_kind,
            resource_id=access.resource.resource.resource_id,
            access_level=ShareAccessLevel.VIEW,
            expected_authority_generation=access.authority_generation,
        )
        if not current.allowed:
            raise CollaborationNotFoundError()

    async def _comment(
        self,
        comment_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> CollaborationComment | None:
        return cast(
            CollaborationComment | None,
            await self.session.scalar(
                select(CollaborationComment).where(
                    CollaborationComment.comment_id == comment_id,
                    CollaborationComment.workspace_id == workspace_id,
                )
            ),
        )

    async def _revision(
        self,
        revision_id: uuid.UUID,
        comment_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> CollaborationCommentRevision | None:
        return cast(
            CollaborationCommentRevision | None,
            await self.session.scalar(
                select(CollaborationCommentRevision).where(
                    CollaborationCommentRevision.revision_id == revision_id,
                    CollaborationCommentRevision.comment_id == comment_id,
                    CollaborationCommentRevision.workspace_id == workspace_id,
                )
            ),
        )

    async def _comment_transition(
        self,
        comment_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> CollaborationCommentTransition | None:
        return cast(
            CollaborationCommentTransition | None,
            await self.session.scalar(
                select(CollaborationCommentTransition)
                .where(
                    CollaborationCommentTransition.comment_id == comment_id,
                    CollaborationCommentTransition.workspace_id == workspace_id,
                )
                .order_by(CollaborationCommentTransition.sequence.desc())
                .limit(1)
            ),
        )

    async def _thread_transition(
        self,
        thread_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> CollaborationCommentThreadTransition | None:
        return cast(
            CollaborationCommentThreadTransition | None,
            await self.session.scalar(
                select(CollaborationCommentThreadTransition)
                .where(
                    CollaborationCommentThreadTransition.thread_id == thread_id,
                    CollaborationCommentThreadTransition.workspace_id == workspace_id,
                )
                .order_by(CollaborationCommentThreadTransition.sequence.desc())
                .limit(1)
            ),
        )

    async def _record(self, comment: CollaborationComment) -> CommentRecord | None:
        thread = await self.session.get(CollaborationCommentThread, comment.thread_id)
        thread_transition = await self._thread_transition(comment.thread_id, comment.workspace_id)
        transition = await self._comment_transition(comment.comment_id, comment.workspace_id)
        if thread is None or thread_transition is None or transition is None:
            return None
        revision = (
            await self.session.get(
                CollaborationCommentRevision,
                transition.visible_revision_id,
            )
            if transition.visible_revision_id is not None
            else None
        )
        return CommentRecord(thread, thread_transition, comment, transition, revision)

    async def _event(
        self,
        *,
        event_type: str,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID | None,
        subject_id: uuid.UUID,
        related_id: uuid.UUID | None,
        source: str,
        trace_id: uuid.UUID,
        audit_event_id: uuid.UUID,
        payload: dict[str, JsonValue],
    ) -> None:
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise CollaborationNotFoundError()
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=workspace.owner_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                subject_id=subject_id,
                actor_user_id=principal.user_id,
                source_identity=source,
                trace_id=trace_id,
                audit_event_id=audit_event_id,
                related_id=related_id,
                payload=payload,
                origin_type="authenticated_user",
            )
        )


class CollaborationActivityService:
    """Audience-aware read over the existing activity-v1 projection."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.authorization = CollaborationAuthorizationService(session)
        self.sharing = SharingService(session)

    async def list_activity(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        resource_kind: ShareResourceKind | str | None = None,
        resource_id: uuid.UUID | None = None,
        event_type: CollaborationActivityKind | str | None = None,
        limit: int = ACTIVITY_PAGE_DEFAULT,
        offset: int = 0,
    ) -> list[CollaborationActivityRecord]:
        if (
            not 1 <= limit <= ACTIVITY_PAGE_MAX
            or not 0 <= offset <= 100_000
            or ((resource_kind is None) != (resource_id is None))
        ):
            raise CollaborationValidationError()
        decision = await self.authorization.evaluate(
            principal=principal,
            workspace_id=workspace_id,
            action=CollaborationAction.COLLABORATION_ACTIVITY_LIST,
        )
        if not decision.allowed or decision.authority_generation is None:
            raise CollaborationNotFoundError()
        requested_kind: ShareResourceKind | None = None
        if resource_kind is not None:
            try:
                requested_kind = ShareResourceKind(resource_kind)
            except ValueError as exc:
                raise CollaborationNotFoundError() from exc
            assert resource_id is not None
            access = await self.sharing.evaluate_access(
                principal=principal,
                workspace_id=workspace_id,
                resource_kind=requested_kind,
                resource_id=resource_id,
                expected_authority_generation=decision.authority_generation,
            )
            if not access.allowed:
                raise CollaborationNotFoundError()
        requested_event: CollaborationActivityKind | None = None
        if event_type is not None:
            try:
                requested_event = CollaborationActivityKind(event_type)
            except ValueError as exc:
                raise CollaborationValidationError() from exc
        allowed_types = [kind.value for kind in CollaborationActivityKind]
        statement = (
            select(DomainActivityEntry, DomainEventRecord)
            .join(DomainEventRecord, DomainEventRecord.event_id == DomainActivityEntry.event_id)
            .join(DomainEventOutbox, DomainEventOutbox.event_id == DomainEventRecord.event_id)
            .where(
                DomainActivityEntry.workspace_id == workspace_id,
                DomainEventOutbox.delivery_state == "delivered",
                DomainEventRecord.event_type.in_(allowed_types),
            )
            .order_by(
                DomainActivityEntry.sequence.desc(),
                DomainActivityEntry.activity_id.desc(),
            )
        )
        if requested_event is not None:
            statement = statement.where(DomainEventRecord.event_type == requested_event.value)
        rows = (await self.session.execute(statement.limit(2_000))).all()
        visible: list[CollaborationActivityRecord] = []
        for activity, event in rows:
            scope = await self._event_resource(event)
            if scope is None:
                continue
            kind, scoped_resource_id, comment_id, thread_id = scope
            if requested_kind is not None and (
                kind is not requested_kind or scoped_resource_id != resource_id
            ):
                continue
            access = await self.sharing.evaluate_access(
                principal=principal,
                workspace_id=workspace_id,
                resource_kind=kind,
                resource_id=scoped_resource_id,
                expected_authority_generation=decision.authority_generation,
            )
            if not access.allowed:
                continue
            visible.append(
                CollaborationActivityRecord(
                    activity_id=activity.activity_id,
                    event_id=event.event_id,
                    event_type=CollaborationActivityKind(event.event_type),
                    workspace_id=workspace_id,
                    canvas_id=event.canvas_id,
                    sequence=event.sequence,
                    resource_kind=kind,
                    resource_id=scoped_resource_id,
                    comment_id=comment_id,
                    thread_id=thread_id,
                    actor_user_id=event.actor_user_id,
                    trace_id=event.trace_id,
                    occurred_at=event.occurred_at,
                )
            )
            if len(visible) >= offset + limit:
                break
        return visible[offset : offset + limit]

    async def _event_resource(
        self,
        event: DomainEventRecord,
    ) -> tuple[ShareResourceKind, uuid.UUID, uuid.UUID | None, uuid.UUID | None] | None:
        if event.subject_kind == "comment":
            comment = await self.session.get(CollaborationComment, event.subject_id)
            if comment is None or comment.workspace_id != event.workspace_id:
                return None
            return (
                ShareResourceKind(comment.resource_kind),
                comment.resource_id,
                comment.comment_id,
                comment.thread_id,
            )
        if event.subject_kind == "comment_thread":
            thread = await self.session.get(CollaborationCommentThread, event.subject_id)
            if thread is None or thread.workspace_id != event.workspace_id:
                return None
            return (
                ShareResourceKind(thread.resource_kind),
                thread.resource_id,
                None,
                thread.thread_id,
            )
        resource_id = (
            event.subject_id if event.subject_kind == "collaboration_resource" else event.related_id
        )
        if resource_id is None:
            return None
        resource_kind = event.payload.get("resourceKind")
        if not isinstance(resource_kind, str):
            return None
        try:
            kind = ShareResourceKind(resource_kind)
        except ValueError:
            return None
        return kind, resource_id, None, None


def _normalize_content(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFC",
        value.replace("\r\n", "\n").replace("\r", "\n"),
    ).strip()
    if (
        not normalized
        or len(normalized) > COMMENT_MAX_LENGTH
        or _UNSAFE_CONTENT.search(normalized)
        or _CONTROL_CONTENT.search(normalized)
    ):
        raise CollaborationValidationError()
    return normalized


def _content_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _reason_code(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", normalized):
        raise CollaborationValidationError()
    return normalized


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ACTIVITY_PAGE_DEFAULT",
    "ACTIVITY_PAGE_MAX",
    "COMMENTS_PER_THREAD_MAX",
    "COMMENT_CREATION_RATE_PER_MINUTE",
    "COMMENT_MAX_DEPTH",
    "COMMENT_MAX_LENGTH",
    "COMMENT_PAGE_DEFAULT",
    "COMMENT_PAGE_MAX",
    "CollaborationActivityKind",
    "CollaborationActivityRecord",
    "CollaborationActivityService",
    "CommentRecord",
    "CommentRevisionKind",
    "CommentService",
    "CommentState",
    "CommentThreadState",
    "CommentTombstoneKind",
    "RevisionRecord",
    "ThreadRecord",
]
