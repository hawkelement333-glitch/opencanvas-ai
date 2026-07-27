# Milestone 6.1 Handoff — Workspace Memberships and Invitations

Date: 2026-07-25

Branch: `milestone-6-1-workspace-memberships-invitations-local`

Architecture parent: `4771bea508d4fa8ec90edb4ed90de4efb444101a`

Status: complete locally; no upstream and no remote operation

Next checkpoint: 6.2 — Collaboration Roles and Permission Authority

Post-handoff PostgreSQL compatibility note: later live PostgreSQL 17
validation proved that migration `0021`'s textual
`ck_workspace_membership_transition_role` check leaves `current_role`
unquoted, so PostgreSQL resolves it as session expression `CURRENT_ROLE`
rather than the transition row's column. The
[migration 0021 current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
selects one quoted-column correction for the migration and matching ORM
metadata. The historical SQLite/offline validation ledger below remains
accurate for this checkpoint, but it is not live PostgreSQL constraint proof.
With that candidate correction present, later validation proved that
`_backfill_owner_memberships()` also leaves `current_role` bare in its raw
transition `INSERT` target list. The
[migration 0021 owner-backfill current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
authorizes only the corresponding quoted target identifier and exact
PostgreSQL/SQLite backfill proof. Membership, invitation, owner-backfill, role,
workspace-scope, ownership, and history semantics are unchanged.

## Completed scope

Milestone 6.1 establishes the collaboration identity boundary without
implementing generalized role authority:

- immutable workspace-membership identity bound to one exact user/workspace;
- append-only membership state and single-role evidence;
- immutable invitation identity separate from membership;
- append-only invitation lifecycle, secret versions, and delivery attempts;
- scoped request idempotency identities;
- deterministic existing-workspace owner-membership backfill;
- atomic owner membership for every new workspace path;
- monotonic workspace authority generation for membership activation;
- centralized membership and invitation services;
- authenticated, CSRF-protected, tenant-scoped APIs;
- existing domain events, transactional outbox, activity, Trace, and
  collaboration audit integration.

The closed role vocabulary is `owner`, `administrator`, `editor`, `approver`,
`member`, and `viewer`. Invitations cannot assign `owner`. A role is persisted
as a collaboration ceiling only; it grants no Milestone 4 capability,
approval, context, mutation, workflow, or agent authority.

## Migration and persistence

Migration `20260725_0021` has direct parent `20260725_0020` and is the sole
Alembic head. It adds:

- `workspace_memberships`
- `workspace_membership_transitions`
- `workspace_invitations`
- `workspace_invitation_transitions`
- `workspace_invitation_secret_versions`
- `workspace_invitation_delivery_attempts`
- `collaboration_request_identities`
- `workspace_authority_versions`
- `collaboration_audit_events`

Composite scope foreign keys bind membership and invitation evidence to the
same user and workspace. Closed checks cover policy version, roles, lifecycle,
delivery state, digests, expiration ordering, and positive authority
generations. Uniqueness and lifecycle triggers prevent duplicate active
memberships, a second owner, duplicate invitation consumption, invalid
transition order, and out-of-order secret/delivery evidence. Immutable
identity, transition, audit, secret, delivery, and idempotency records reject
update and delete in SQLite and PostgreSQL.

The upgrade deterministically derives one owner membership, transition,
collaboration audit event, Trace event, and authority generation 1 for every
existing workspace. Downgrade removes only this deterministic backfill
evidence and the 6.1 schema, then restores the prior domain-event constraints.
Upgrade, downgrade, and re-upgrade preserve one sole head.

## Invitation lifecycle and security

The closed invitation lifecycle is:

```text
pending -> accepted | declined | expired | revoked
```

Creation accepts only server-validated normalized email, one closed non-owner
role, server-bounded expiration, and scoped idempotency. The service creates a
cryptographically random token but persists only a keyed HMAC-SHA-256 digest
under the dedicated invitation secret. Raw tokens are confined to the
delivery boundary; development/test mode may return the one newly issued
token for local testing, while list/replay responses never return it.

Acceptance requires an authenticated principal whose normalized email exactly
matches the invitation recipient. The supplied token must match the latest
secret version. Resend appends a new secret version, invalidates all older
tokens, and is limited to no sooner than 10 minutes and five resends per 24
hours. Wrong-user, wrong-token, malformed, cross-tenant, expired, revoked,
declined, or probed requests return bounded safe errors without enumeration.

Successful first acceptance atomically creates the exact membership and
active role transition, consumes the invitation, increments workspace
authority generation, and records idempotency, audit, Trace, domain events,
and outbox evidence. An exact replay returns the same membership. Concurrent
delivery is constrained to one membership; a loser safely re-reads or returns
a bounded conflict. If the exact user already has an active membership, the
invitation is consumed against that stable membership without creating a
duplicate or incrementing authority again.

## Limits

- 500 active memberships per workspace
- 100 active workspaces per user
- 100 pending invitations per workspace
- 7-day default invitation lifetime
- 30-day maximum invitation lifetime
- 10-minute minimum resend interval
- 5 resends per invitation per 24 hours
- list page default 50
- list page maximum 100

All timestamps, limits, lifecycle state, scope, and identity resolution are
server-owned.

## Services and APIs

`MembershipService` owns exact active membership resolution, owner bootstrap,
owner-only 6.1 administration checks, scoped listing, and authority baseline.
`InvitationService` owns normalization, lifecycle, credentials, limits,
idempotency, recipient binding, concurrency behavior, events, audit, Trace,
and delivery evidence. Routes translate only validated schemas and safe
domain errors.

Implemented APIs:

```text
GET  /api/v1/workspaces
GET  /api/v1/workspaces/{workspaceId}/memberships
POST /api/v1/workspaces/{workspaceId}/invitations
GET  /api/v1/workspaces/{workspaceId}/invitations
POST /api/v1/workspaces/{workspaceId}/invitations/{invitationId}/resend
POST /api/v1/workspaces/{workspaceId}/invitations/{invitationId}/revoke
POST /api/v1/collaboration-invitations/{invitationId}/accept
POST /api/v1/collaboration-invitations/{invitationId}/decline
```

Workspace listing now includes only exact active memberships plus the
preserved owner fallback. It does not expose canvases or resources merely
because membership exists.

## Events, outbox, activity, Trace, and audit

The existing closed event registry now includes:

- `invitation.created`
- `invitation.accepted`
- `invitation.declined`
- `invitation.expired`
- `invitation.revoked`
- `membership.activated`

Each event uses the existing workspace sequence, provenance record,
transactional outbox, and activity projector. Payloads contain only bounded
state, role, reason, membership identity, and authority generation where
applicable. They contain no email, token, token digest, session, private
authority, or reasoning.

Meaningful invitation operations have started/succeeded Trace pairs linked to
the exact workspace, actor, invitation, operation, and safe result.
Collaboration audit events retain action, outcome, reason, trace, and a digest
of safe metadata. Failure injection proves that rollback removes the proposed
membership, invitation transition, authority increment, idempotency identity,
audit, Trace, event, and outbox evidence together.

## Concrete defects found and fixed

The audit proved and corrected:

1. Runtime ORM audit foreign keys did not mirror migration foreign keys,
   allowing SQLite to schedule an invitation transition before its audit or
   result membership. Runtime mappings now declare the dependencies, and
   acceptance explicitly flushes the membership dependency inside the same
   transaction.
2. The in-memory SQLite test fixture shared one connection across concurrent
   requests, allowing one rollback to interfere with another transaction.
   Tests now use an isolated temporary file-backed database.
3. Existing account hard deletion conflicted with new append-only
   collaboration evidence. Account deletion now tombstones the workspace and
   anonymizes/deactivates the user while preserving immutable audit
   identities; mutable user content is still deleted.
4. Prior migration-head validators still expected `20260725_0020`, and the
   generic domain-event registry test synthesized invalid collaboration
   subjects. Validators now expect `20260725_0021`; collaboration event scope
   is exercised through real invitation/membership integration tests.
5. PostgreSQL lacked the SQLite-equivalent secret-version and
   delivery-attempt sequence triggers. Both dialects now enforce ordered
   append-only invitation evidence.
6. Resend delivery attempts initially inherited the invitation-creation Trace.
   Issuance now carries the exact create/resend Trace through the delivery
   boundary, and focused tests assert the rotated secret’s delivery evidence
   links to the resend Trace.

## Tests added

- migration cycle, sole head, deterministic owner backfill, append-only
  guards, duplicate owner/membership rejection, secret-column inspection, and
  PostgreSQL offline DDL;
- authorized/unauthorized invitation creation, CSRF, tenant isolation,
  masking, safe listing, idempotency collision, exact-recipient acceptance,
  wrong-user denial, replay, revocation, decline, and safe errors;
- concurrent duplicate acceptance with exactly one membership;
- expiration bounds, pending-invitation limit, membership limit, explicit
  expiry transition, and unchanged authority on denial;
- resend rotation, stale-token denial, existing-membership reuse, and exact
  authority generation;
- transaction failure injection proving no partial state or evidence;
- event, outbox, activity, audit, Trace, and workspace-list integration.

## Validation

Backend:

- focused and affected suite: 38 passed, 0 failed, 0 skipped, 30 warnings;
- explicit security-marked suite: 35 passed, 0 failed, 0 skipped;
- full backend suite: 496 passed, 0 failed, 1 skipped, 36 warnings;
- skipped test: configured PostgreSQL runtime integration when no PostgreSQL
  URL is available;
- warnings: 35 Python 3.12 SQLite datetime-adapter deprecations and 1 upstream
  FastAPI/Starlette 422-status deprecation;
- strict production mypy: passed;
- Ruff lint and format: passed;
- Python compilation and ORM mapper/import validation: passed;
- migration upgrade/downgrade/re-upgrade and PostgreSQL offline DDL: passed.

Frontend:

- ESLint: passed with zero warnings;
- TypeScript `--noEmit`: passed;
- Vitest: 15 files and 66 tests passed;
- Next.js production build: passed with 8 routes generated;
- Chromium smoke: 6 passed and 2 real-service scenarios skipped because their
  optional PostgreSQL/FastAPI environment was not configured.

Repository:

- Prettier repository formatting: passed;
- migration validator: upgrade `20260725_0021`, downgrade
  `20260725_0020`, re-upgrade `20260725_0021`;
- repository hygiene and secret scan: passed for 324 source files;
- whitespace and `git diff --check`: passed;
- local-path and prohibited-scope scans: passed;
- Git object integrity and protected-reference verification: passed before
  commit and repeated after commit.

The bundled `pnpm` wrapper attempted dependency installation before each
frontend script and stopped on its existing ignored-build policy for
`sharp`/`unrs-resolver`. No dependency approval or package configuration was
changed. Equivalent locked, installed workspace executables were invoked
directly for the successful frontend checks above.

## Bounded limitations and next boundary

Milestone 6.2 is not started. This checkpoint deliberately does not add:

- generalized role-permission evaluation or collaboration permission
  registry;
- non-owner invitation administration;
- role changes or membership suspension, restoration, or removal;
- approval eligibility or authority assignments;
- resource, canvas, workflow, or agent sharing;
- ownership transfer or full revocation fencing;
- comments, collaboration administration UI, or multi-workspace navigation;
- Advanced Real-Time Collaboration, live cursors, presence, CRDT, OT, offline
  merging, or reconnect conflict resolution;
- Milestone 7 Indexer, Milestone 9 Librarian, Agent Society, deployment, or
  release work.

Migrations `20260725_0022` and `20260725_0023` were not created.
