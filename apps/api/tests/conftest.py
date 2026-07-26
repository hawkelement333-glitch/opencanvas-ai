from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import get_database, get_session
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Base,
    CollaborationAuditEvent,
    User,
    Workspace,
    WorkspaceAuthorityVersion,
    WorkspaceMembership,
    WorkspaceMembershipTransition,
)
from opencanvas_api.db.session import Database
from opencanvas_api.main import create_app


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database_path = (tmp_path / "test.db").as_posix()
    database = Database(f"sqlite+aiosqlite:///{database_path}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.sessions() as session:
        session.add(
            User(
                id=SYSTEM_USER_ID,
                email="test-system@mobius.invalid",
                email_normalized="test-system@mobius.invalid",
                password_hash="test-only",
                display_name="Test system user",
                email_verified=True,
            )
        )
        workspace = Workspace(
            id=SYSTEM_WORKSPACE_ID,
            owner_id=SYSTEM_USER_ID,
            name="Test workspace",
        )
        session.add(workspace)
        await session.flush()
        now = datetime.now(UTC)
        membership_id = uuid.uuid5(SYSTEM_WORKSPACE_ID, "owner-membership")
        trace_id = uuid.uuid5(membership_id, "bootstrap-trace")
        audit_id = uuid.uuid5(membership_id, "bootstrap-audit")
        session.add(
            WorkspaceAuthorityVersion(
                workspace_id=SYSTEM_WORKSPACE_ID,
                authority_generation=1,
                last_trace_id=trace_id,
                updated_at=now,
            )
        )
        session.add(
            CollaborationAuditEvent(
                audit_event_id=audit_id,
                workspace_id=SYSTEM_WORKSPACE_ID,
                actor_user_id=SYSTEM_USER_ID,
                subject_kind="workspace_membership",
                subject_id=membership_id,
                action="membership.test_bootstrap",
                outcome="succeeded",
                reason_code="test_owner_bootstrap",
                metadata_digest=hashlib.sha256(b"test-owner-bootstrap").hexdigest(),
                trace_id=trace_id,
                recorded_at=now,
            )
        )
        session.add(
            WorkspaceMembership(
                membership_id=membership_id,
                user_id=SYSTEM_USER_ID,
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
                transition_id=uuid.uuid5(membership_id, "bootstrap-transition"),
                membership_id=membership_id,
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                sequence=0,
                previous_state=None,
                current_state="active",
                previous_role=None,
                current_role="owner",
                reason_code="test_owner_bootstrap",
                collaboration_policy_version="collaboration-policy-v1",
                authority_generation=1,
                actor_user_id=SYSTEM_USER_ID,
                trace_id=trace_id,
                audit_event_id=audit_id,
                recorded_at=now,
            )
        )
        await session.commit()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def app(database: Database, tmp_path: Path) -> FastAPI:
    application = create_app()
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        ai_context_character_limit=10_000,
        document_storage_root=tmp_path / "documents",
        embedding_provider="mock",
        auth_test_bypass=True,
    )

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with database.sessions() as session:
            yield session

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_database] = lambda: database
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


@pytest.fixture
def api_prefix() -> str:
    return "/api/v1"
