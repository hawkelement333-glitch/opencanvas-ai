from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

import opencanvas_api.services.collaboration as collaboration
from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    CollaborationAuditEvent,
    CollaborationRequestIdentity,
    DomainEventRecord,
    TraceEvent,
    User,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceInvitationDeliveryAttempt,
    WorkspaceInvitationTransition,
    WorkspaceMembership,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration import (
    CollaborationLimitError,
    CollaborationNotFoundError,
    CollaborationValidationError,
    InvitationExpiredError,
    InvitationService,
    MembershipService,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        embedding_provider="mock",
        document_storage_root=tmp_path / "documents",
        auth_test_bypass=True,
        session_secret="test-session-secret-that-is-long-enough-2026",
        invitation_secret="test-invitation-secret-that-is-distinct-2026",
    )


def _principal(user: User) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email_normalized,
        display_name=user.display_name,
        session_id=uuid.uuid4(),
        csrf_token_hash="test-csrf",
    )


async def _seed_workspace(
    database: Database,
) -> tuple[uuid.UUID, Principal, Principal]:
    async with database.sessions() as session:
        owner = User(
            id=uuid.uuid4(),
            email="service-owner@example.test",
            email_normalized="service-owner@example.test",
            password_hash="test-only",
            display_name="Service owner",
            email_verified=True,
        )
        recipient = User(
            id=uuid.uuid4(),
            email="service-recipient@example.test",
            email_normalized="service-recipient@example.test",
            password_hash="test-only",
            display_name="Service recipient",
            email_verified=True,
        )
        workspace = Workspace(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Service workspace",
        )
        session.add_all((owner, recipient, workspace))
        await session.flush()
        await MembershipService(session).bootstrap_owner_membership(
            workspace=workspace,
            actor_user_id=owner.id,
        )
        await session.commit()
        return workspace.id, _principal(owner), _principal(recipient)


@pytest.mark.security
async def test_invitation_expiration_bounds_pending_limit_and_membership_limit(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, owner, recipient = await _seed_workspace(database)
    settings = _settings(tmp_path)
    base_time = datetime(2026, 7, 25, 12, tzinfo=UTC)

    async with database.sessions() as session:
        service = InvitationService(
            session,
            settings=settings,
            now_factory=lambda: base_time,
        )
        with pytest.raises(CollaborationValidationError):
            await service.create(
                principal=owner,
                workspace_id=workspace_id,
                recipient_email=recipient.email,
                intended_role="viewer",
                idempotency_key="invalid-expiry-low",
                expires_in_days=0,
            )
        with pytest.raises(CollaborationValidationError):
            await service.create(
                principal=owner,
                workspace_id=workspace_id,
                recipient_email=recipient.email,
                intended_role="viewer",
                idempotency_key="invalid-expiry-high",
                expires_in_days=31,
            )
        issued = await service.create(
            principal=owner,
            workspace_id=workspace_id,
            recipient_email=recipient.email,
            intended_role="viewer",
            idempotency_key="expiry-create-001",
            expires_in_days=1,
        )
        await session.commit()
        assert issued.view.invitation.expires_at == base_time + timedelta(days=1)

    monkeypatch.setattr(
        collaboration,
        "PENDING_INVITATION_LIMIT_PER_WORKSPACE",
        1,
    )
    async with database.sessions() as session:
        with pytest.raises(CollaborationLimitError):
            await InvitationService(
                session,
                settings=settings,
                now_factory=lambda: base_time,
            ).create(
                principal=owner,
                workspace_id=workspace_id,
                recipient_email="second-recipient@example.test",
                intended_role="member",
                idempotency_key="pending-limit-001",
            )
        await session.rollback()

    future = base_time + timedelta(days=2)
    async with database.sessions() as session:
        service = InvitationService(
            session,
            settings=settings,
            now_factory=lambda: future,
        )
        with pytest.raises(InvitationExpiredError) as expired:
            await service.accept(
                principal=recipient,
                invitation_id=issued.view.invitation.invitation_id,
                raw_token=issued.raw_token or "",
                idempotency_key="expiry-accept-001",
            )
        assert expired.value.transition_persisted is True
        await session.commit()

    async with database.sessions() as session:
        invitation_id = issued.view.invitation.invitation_id
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceInvitationTransition)
                .where(
                    WorkspaceInvitationTransition.invitation_id == invitation_id,
                    WorkspaceInvitationTransition.current_state == "expired",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.accepted_invitation_id == invitation_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DomainEventRecord)
                .where(
                    DomainEventRecord.workspace_id == workspace_id,
                    DomainEventRecord.event_type == "invitation.expired",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(
                    TraceEvent.workspace_id == workspace_id,
                    TraceEvent.operation == "expired_invitation",
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(WorkspaceAuthorityVersion.authority_generation).where(
                    WorkspaceAuthorityVersion.workspace_id == workspace_id
                )
            )
            == 1
        )

    async with database.sessions() as session:
        service = InvitationService(
            session,
            settings=settings,
            now_factory=lambda: future,
        )
        limit_invitation = await service.create(
            principal=owner,
            workspace_id=workspace_id,
            recipient_email=recipient.email,
            intended_role="member",
            idempotency_key="membership-limit-create",
        )
        await session.commit()

    monkeypatch.setattr(collaboration, "MEMBERSHIP_LIMIT_PER_WORKSPACE", 1)
    async with database.sessions() as session:
        with pytest.raises(CollaborationLimitError):
            await InvitationService(
                session,
                settings=settings,
                now_factory=lambda: future,
            ).accept(
                principal=recipient,
                invitation_id=limit_invitation.view.invitation.invitation_id,
                raw_token=limit_invitation.raw_token or "",
                idempotency_key="membership-limit-accept",
            )
        await session.rollback()


@pytest.mark.security
async def test_resend_rotates_secret_and_existing_membership_is_reused(
    database: Database,
    tmp_path: Path,
) -> None:
    workspace_id, owner, recipient = await _seed_workspace(database)
    settings = _settings(tmp_path)
    base_time = datetime(2026, 7, 25, 12, tzinfo=UTC)

    async with database.sessions() as session:
        service = InvitationService(
            session,
            settings=settings,
            now_factory=lambda: base_time,
        )
        first = await service.create(
            principal=owner,
            workspace_id=workspace_id,
            recipient_email=recipient.email,
            intended_role="editor",
            idempotency_key="rotation-create-001",
        )
        await service.record_delivery(
            invitation_id=first.view.invitation.invitation_id,
            workspace_id=workspace_id,
            secret_sequence=first.secret_sequence or 0,
            channel="development_token",
            outcome="delivered",
            trace_id=first.view.invitation.creation_trace_id,
        )
        await session.commit()

    resend_time = base_time + timedelta(minutes=11)
    async with database.sessions() as session:
        service = InvitationService(
            session,
            settings=settings,
            now_factory=lambda: resend_time,
        )
        resent = await service.resend(
            principal=owner,
            workspace_id=workspace_id,
            invitation_id=first.view.invitation.invitation_id,
            idempotency_key="rotation-resend-001",
        )
        assert resent.raw_token and resent.raw_token != first.raw_token
        assert resent.secret_sequence == 1
        await service.record_delivery(
            invitation_id=resent.view.invitation.invitation_id,
            workspace_id=workspace_id,
            secret_sequence=resent.secret_sequence,
            channel="development_token",
            outcome="delivered",
            trace_id=resent.trace_id,
        )
        await session.commit()

    async with database.sessions() as session:
        service = InvitationService(
            session,
            settings=settings,
            now_factory=lambda: resend_time,
        )
        with pytest.raises(CollaborationNotFoundError):
            await service.accept(
                principal=recipient,
                invitation_id=first.view.invitation.invitation_id,
                raw_token=first.raw_token or "",
                idempotency_key="rotation-old-token",
            )
        accepted = await service.accept(
            principal=recipient,
            invitation_id=first.view.invitation.invitation_id,
            raw_token=resent.raw_token or "",
            idempotency_key="rotation-accept-001",
        )
        first_membership_id = accepted.membership.membership.membership_id
        await session.commit()

    async with database.sessions() as session:
        service = InvitationService(
            session,
            settings=settings,
            now_factory=lambda: resend_time,
        )
        second = await service.create(
            principal=owner,
            workspace_id=workspace_id,
            recipient_email=recipient.email,
            intended_role="viewer",
            idempotency_key="existing-create-001",
        )
        reused = await service.accept(
            principal=recipient,
            invitation_id=second.view.invitation.invitation_id,
            raw_token=second.raw_token or "",
            idempotency_key="existing-accept-001",
        )
        assert reused.duplicate is True
        assert reused.membership.membership.membership_id == first_membership_id
        await session.commit()

    async with database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(
                    WorkspaceMembership.user_id == recipient.user_id,
                    WorkspaceMembership.workspace_id == workspace_id,
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(WorkspaceAuthorityVersion.authority_generation).where(
                    WorkspaceAuthorityVersion.workspace_id == workspace_id
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(WorkspaceInvitationDeliveryAttempt.trace_id).where(
                    WorkspaceInvitationDeliveryAttempt.invitation_id
                    == first.view.invitation.invitation_id,
                    WorkspaceInvitationDeliveryAttempt.secret_sequence == 1,
                )
            )
            == resent.trace_id
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(
                    TraceEvent.workspace_id == workspace_id,
                    TraceEvent.operation == "resend_invitation",
                )
            )
            == 2
        )


@pytest.mark.security
async def test_acceptance_failure_rolls_back_all_state_and_evidence(
    database: Database,
    tmp_path: Path,
) -> None:
    workspace_id, owner, recipient = await _seed_workspace(database)
    settings = _settings(tmp_path)

    async with database.sessions() as session:
        service = InvitationService(session, settings=settings)
        issued = await service.create(
            principal=owner,
            workspace_id=workspace_id,
            recipient_email=recipient.email,
            intended_role="member",
            idempotency_key="rollback-create-001",
        )
        await session.commit()

    async with database.sessions() as session:
        service = InvitationService(session, settings=settings)
        service.events.record = AsyncMock(side_effect=RuntimeError("injected event failure"))
        with pytest.raises(RuntimeError, match="injected event failure"):
            await service.accept(
                principal=recipient,
                invitation_id=issued.view.invitation.invitation_id,
                raw_token=issued.raw_token or "",
                idempotency_key="rollback-accept-001",
            )
        await session.rollback()

    async with database.sessions() as session:
        invitation_id = issued.view.invitation.invitation_id
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.accepted_invitation_id == invitation_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceInvitationTransition)
                .where(
                    WorkspaceInvitationTransition.invitation_id == invitation_id,
                    WorkspaceInvitationTransition.current_state == "accepted",
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationRequestIdentity)
                .where(
                    CollaborationRequestIdentity.workspace_id == workspace_id,
                    CollaborationRequestIdentity.operation == "invitation.accept",
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CollaborationAuditEvent)
                .where(
                    CollaborationAuditEvent.workspace_id == workspace_id,
                    CollaborationAuditEvent.action.in_(
                        ("invitation.accept", "membership.activate")
                    ),
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TraceEvent)
                .where(
                    TraceEvent.workspace_id == workspace_id,
                    TraceEvent.operation == "accept_invitation",
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DomainEventRecord)
                .where(
                    DomainEventRecord.workspace_id == workspace_id,
                    DomainEventRecord.event_type == "invitation.accepted",
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(WorkspaceAuthorityVersion.authority_generation).where(
                    WorkspaceAuthorityVersion.workspace_id == workspace_id
                )
            )
            == 1
        )
