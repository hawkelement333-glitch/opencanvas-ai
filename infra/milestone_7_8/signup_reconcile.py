"""Read-only recovery classification for the two synthetic pilot signups."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid5

SLOTS = {
    "primary": "M78 synthetic pilot operator",
    "secondary": "M78 negative scope user",
}
STAGING_OPERATOR_DENY_ALL = "00000000-0000-0000-0000-000000000001"
SEED_EMAIL = "migration-principal@mobius.invalid"


def email_binding(email: str, nonce: str) -> str:
    return hashlib.sha256(
        b"m78/signup-slot/v1\0"
        + bytes.fromhex(nonce)
        + email.strip().casefold().encode()
    ).hexdigest()


def account_actions(slots: dict, *, writers_quiesced: bool) -> dict[str, str]:
    """A snapshot is actionable only after the earlier writer is terminal and fenced."""
    if (
        not writers_quiesced
        or slots.keys() != SLOTS.keys()
        or any(
            not isinstance(slot, dict)
            or slot.get("state") not in {"absent", "complete"}
            for slot in slots.values()
        )
        or (
            slots["primary"]["state"] == "absent"
            and slots["secondary"]["state"] == "complete"
        )
    ):
        return dict.fromkeys(SLOTS, "hold")
    return {
        name: "retry" if slot["state"] == "absent" else "resume"
        for name, slot in slots.items()
    }


async def inspect_signup(
    session, bindings: dict[str, str], nonce: str, not_before: datetime
) -> dict:
    from sqlalchemy import select
    from sqlalchemy.orm import load_only

    from opencanvas_api.db.models import SYSTEM_USER_ID, TraceEvent, User

    if (
        set(bindings) != set(SLOTS)
        or len(set(bindings.values())) != len(SLOTS)
        or any(len(bytes.fromhex(value)) != 32 for value in bindings.values())
        or len(bytes.fromhex(nonce)) != 32
        or not_before.tzinfo is None
    ):
        raise ValueError("exact distinct signup bindings and attempt window required")
    users = (
        await session.execute(
            select(
                User.id,
                User.email,
                User.email_normalized,
                User.display_name,
                User.is_active,
                User.email_verified,
                User.deleted_at,
                User.settings_payload,
                User.created_at,
                (User.password_hash == "login-disabled").label("login_disabled"),
                User.password_hash.like("scrypt$%").label("has_password"),
            ).limit(4)
        )
    ).all()
    seed = next((user for user in users if user.id == SYSTEM_USER_ID), None)
    valid_seed = bool(
        seed
        and seed.email == seed.email_normalized == SEED_EMAIL
        and seed.login_disabled
        and seed.display_name == "Migrated local data"
        and seed.is_active
        and seed.email_verified
        and seed.deleted_at is None
        and seed.settings_payload == {"migrationPrincipal": True}
    )
    matches = {}
    for user in users:
        if user.id == SYSTEM_USER_ID:
            continue
        role = next(
            (
                role
                for role, digest in bindings.items()
                if digest == email_binding(user.email_normalized, nonce)
            ),
            None,
        )
        if role is None or role in matches:
            return {
                "seedMatched": valid_seed,
                "slots": dict.fromkeys(SLOTS, {"state": "ambiguous"}),
            }
        matches[role] = user

    # Audit/trace links can outlive their principal. Hold on a non-seed signup
    # trace whose user is outside the exact bound pair, even if users looks empty.
    known_users = [SYSTEM_USER_ID, *(row.id for row in matches.values())]
    orphan = (
        await session.scalars(
            select(TraceEvent)
            .options(load_only(TraceEvent.event_id))
            .where(
                TraceEvent.operation == "bootstrap_owner_membership",
                (TraceEvent.user_id.is_(None) | TraceEvent.user_id.not_in(known_users)),
            )
            .limit(1)
        )
    ).first()
    if not valid_seed or orphan is not None:
        return {
            "seedMatched": valid_seed,
            "slots": dict.fromkeys(SLOTS, {"state": "ambiguous"}),
        }

    slots = {}
    for name in SLOTS:
        if name not in matches:
            slots[name] = {"state": "absent"}
            continue
        user = matches[name]
        created = user.created_at.replace(tzinfo=user.created_at.tzinfo or UTC)
        complete = (
            user.id.version == 4
            and user.is_active
            and not user.email_verified
            and user.deleted_at is None
            and user.has_password
            and user.settings_payload == {}
            and user.email.strip().casefold() == user.email_normalized
            and user.display_name == SLOTS[name]
            and not_before <= created <= datetime.now(UTC)
            and await _signup_effects(session, user.id, SLOTS[name])
        )
        slots[name] = (
            {"state": "complete", "userId": str(user.id)}
            if complete
            else {"state": "ambiguous"}
        )
    return {"seedMatched": True, "slots": slots}


async def _signup_effects(session, user_id: UUID, display_name: str) -> bool:
    from sqlalchemy import select
    from sqlalchemy.orm import load_only

    from opencanvas_api.db.models import (
        CollaborationAuditEvent,
        DomainEventOutbox,
        DomainEventProvenance,
        DomainEventRecord,
        TraceEvent,
        UserSession,
        Workspace,
        WorkspaceAuthorityVersion,
        WorkspaceMembership,
        WorkspaceMembershipTransition,
    )

    async def one(query):
        rows = (await session.scalars(query.limit(2))).all()
        return rows[0] if len(rows) == 1 else None

    workspace = await one(select(Workspace).where(Workspace.owner_id == user_id))
    if (
        workspace is None
        or workspace.name != f"{display_name}'s workspace"
        or workspace.lifecycle_state != "active"
        or workspace.deleted_at is not None
    ):
        return False
    ws = workspace.id
    member = uuid5(ws, "owner-membership")
    trace = uuid5(ws, "owner-membership-trace")
    membership = await one(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == ws,
            WorkspaceMembership.user_id == user_id,
        )
    )
    if (
        membership is None
        or membership.membership_id != member
        or membership.created_by_user_id != user_id
        or membership.accepted_invitation_id is not None
        or membership.creation_trace_id != trace
    ):
        return False
    audit = membership.creation_audit_event_id
    transition = await one(
        select(WorkspaceMembershipTransition).where(
            WorkspaceMembershipTransition.membership_id == member,
        )
    )
    if (
        transition is None
        or transition.transition_id != uuid5(member, "transition:0")
        or transition.user_id != user_id
        or transition.workspace_id != ws
        or transition.sequence != 0
        or transition.current_role != "owner"
        or transition.current_state != "active"
        or transition.previous_role is not None
        or transition.previous_state is not None
        or transition.actor_user_id != user_id
        or transition.trace_id != trace
        or transition.audit_event_id != audit
        or transition.reason_code != "workspace_owner_bootstrap"
        or transition.authority_generation != 1
    ):
        return False
    checks = (
        select(WorkspaceAuthorityVersion.workspace_id).where(
            WorkspaceAuthorityVersion.workspace_id == ws,
            WorkspaceAuthorityVersion.last_trace_id == trace,
            WorkspaceAuthorityVersion.authority_generation == 1,
        ),
        select(CollaborationAuditEvent.audit_event_id).where(
            CollaborationAuditEvent.audit_event_id == audit,
            CollaborationAuditEvent.workspace_id == ws,
            CollaborationAuditEvent.actor_user_id == user_id,
            CollaborationAuditEvent.subject_id == member,
            CollaborationAuditEvent.subject_kind == "workspace_membership",
            CollaborationAuditEvent.action == "membership.bootstrap_owner",
            CollaborationAuditEvent.outcome == "succeeded",
            CollaborationAuditEvent.trace_id == trace,
            CollaborationAuditEvent.reason_code == "workspace_owner_bootstrap",
        ),
        select(UserSession.id).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        ),
    )
    for query in checks:
        if await one(query) is None:
            return False
    trace_rows = (
        await session.scalars(
            select(TraceEvent)
            .options(
                load_only(
                    TraceEvent.status,
                    TraceEvent.user_id,
                    TraceEvent.workspace_id,
                    TraceEvent.object_id,
                    TraceEvent.actor_id,
                    TraceEvent.actor_type,
                    TraceEvent.event_type,
                    TraceEvent.operation,
                )
            )
            .where(TraceEvent.trace_id == trace)
            .limit(3)
        )
    ).all()
    if (
        len(trace_rows) != 2
        or {(row.status, row.object_id) for row in trace_rows}
        != {("started", ws), ("succeeded", member)}
        or any(
            row.user_id != user_id
            or row.workspace_id != ws
            or row.actor_id != str(user_id)
            or row.actor_type != "user"
            or row.event_type != "collaboration.membership"
            or row.operation != "bootstrap_owner_membership"
            for row in trace_rows
        )
    ):
        return False
    event = await one(
        select(DomainEventRecord.event_id).where(
            DomainEventRecord.workspace_id == ws,
            DomainEventRecord.event_type == "membership.activated",
            DomainEventRecord.user_id == user_id,
            DomainEventRecord.actor_user_id == user_id,
            DomainEventRecord.subject_id == member,
            DomainEventRecord.source_identity == f"membership:{member}:activated",
            DomainEventRecord.trace_id == trace,
            DomainEventRecord.audit_event_id == audit,
        )
    )
    if event is None:
        return False
    provenance = await one(
        select(DomainEventProvenance.provenance_id).where(
            DomainEventProvenance.event_id == event,
            DomainEventProvenance.user_id == user_id,
            DomainEventProvenance.workspace_id == ws,
            DomainEventProvenance.actor_user_id == user_id,
            DomainEventProvenance.trace_id == trace,
            DomainEventProvenance.audit_event_id == audit,
            DomainEventProvenance.origin_type == "authenticated_user",
        )
    )
    outbox = await one(
        select(DomainEventOutbox).where(DomainEventOutbox.event_id == event)
    )
    return (
        provenance == uuid5(event, "provenance")
        and outbox is not None
        and outbox.outbox_id == uuid5(event, "outbox")
        and outbox.user_id == user_id
        and outbox.workspace_id == ws
        and outbox.delivery_state == "pending"
        and outbox.attempt_count == outbox.lease_generation == 0
    )


async def native_snapshot(instruction: dict) -> dict:
    """Run on the bound migration job against the original private database."""
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from opencanvas_api.core.config import DatabaseRole, get_settings
    from opencanvas_api.db.session import Database

    settings = get_settings()
    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                actual = (
                    await connection.execute(text("SELECT current_database()"))
                ).scalar_one()
                if actual != "opencanvas" or (
                    connection.engine.url.host != instruction["databaseHost"]
                ):
                    raise ValueError("signup snapshot is outside the bound database")
                other_sessions = (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
                        )
                    )
                ).scalar_one()
                # The operator must independently fence the original private API
                # and hold workers/other proof dispatch before authorizing recovery.
                async with AsyncSession(bind=connection) as session:
                    snapshot = await inspect_signup(
                        session,
                        instruction["emailBindings"],
                        instruction["nonce"],
                        datetime.fromisoformat(instruction["notBefore"]),
                    )
                return {
                    **snapshot,
                    "otherDatabaseClients": other_sessions,
                    "executionId": os.environ["CONTAINER_APP_JOB_EXECUTION_NAME"],
                    "attempt": instruction["attempt"],
                }
    finally:
        await database.dispose()
