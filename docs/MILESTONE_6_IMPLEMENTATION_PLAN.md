# Milestone 6 Implementation Plan — Core Multi-Workspace Collaboration

Date: 2026-07-25

Architecture baseline: `01a38526320560d54033bed510b0f15a7e77eea7`

Status: checkpoints 6.1–6.4 complete locally; checkpoint 6.5 not started

Next checkpoint: 6.5 — Shared Workflow and Agent Governance

## Governing rules

Every checkpoint must:

- begin from a clean, verified local baseline;
- remain on the approved local Milestone 6 branch with no upstream;
- extend existing authentication, authorization seams, Milestone 4 policy,
  Milestone 5 immutable evidence, Trace, events, outbox, activity, and frontend
  patterns;
- derive the actor from the server session and bind exact membership,
  workspace, canvas, resource, role/policy, lifecycle, and authority
  generation;
- treat role and sharing as collaboration eligibility, never as an agent grant
  or approval;
- use closed registries and server maximums;
- append immutable evidence and use optimistic/generation fencing for mutable
  current state;
- add focused cross-user/workspace/canvas tests, idempotency, concurrency, and
  failure injection before broader regression;
- update architecture, plan, progress, and checkpoint handoff documents;
- create and complete any owned migration within that checkpoint, never
  leaving a partial migration for a later checkpoint to rewrite;
- keep committed migrations immutable and use the next unused revision for
  later corrections or newly proved persistence;
- stop at the checkpoint boundary and perform no remote operation.

The repository retains one Alembic head and every migration has one direct
parent. Current checkpoint allocation is 6.1 -> `20260725_0021` (complete),
6.2 -> `20260725_0022` (complete), 6.3 -> `20260725_0023` (complete), and
6.4 -> `20260725_0024` (complete). Milestone 6.5 exclusively owns planned
revision `20260725_0025`, a direct child of `20260725_0024`; it is not
created. Checkpoints 6.6 and 6.7 have no migration assigned.

## Fixed architecture decisions

1. One current closed role per membership. No multi-role union.
2. Role is a permission ceiling; exact resource ownership/share/inheritance is
   also required.
3. No arbitrary permission grants. Exceptions use typed shares, ownership
   transfer, or scoped approval assignments.
4. Workspace membership grants no blanket canvas access.
5. Pre-acceptance states belong to invitations; active membership always has a
   real authenticated user.
6. Workspace ownership has exactly one owner and requires accepted transfer.
7. Creator, owner, membership, action authority, and approval authority remain
   separate.
8. Shared workflow/agent visibility never implies invocation.
9. Reviewer eligibility extends the existing Milestone 4 approval path.
10. Revocation increments authority generations and rechecks every claim,
    provider, retry, effect, result, compensation, and export boundary.
11. Comments are escaped plain text with append-only revisions/tombstones.
12. Domain events/outbox/activity remain the sole durable collaboration feed.
13. PostgreSQL RLS remains optional defense in depth until deliberately
    implemented and runtime-tested.
14. Real-time collaboration retains abstract adapter seams only.

## 6.1 — Workspace Membership and Invitations

Status: complete locally in migration `20260725_0021`. The implementation
follows the scope below and is handed off in
`MILESTONE_6_1_WORKSPACE_MEMBERSHIPS_INVITATIONS_HANDOFF.md`.

### Scope

- immutable membership identity;
- append-only membership state/role transitions;
- closed roles and collaboration policy version;
- secure invitation identity, secret versions, state, delivery, acceptance,
  decline, expiry, revoke, and resend;
- owner-membership backfill and account-creation integration;
- authenticated, CSRF-protected, bounded APIs;
- exact membership/workspace isolation.

### Persistence

Create migration `20260725_0021` only during 6.1:

- `workspace_memberships`
- `workspace_membership_transitions`
- `workspace_invitations`
- `workspace_invitation_transitions`
- `workspace_invitation_secret_versions`
- `workspace_invitation_delivery_attempts`
- `collaboration_request_identities`
- `workspace_authority_versions`
- `collaboration_audit_events`

Required constraints:

- one membership identity per user/workspace admission;
- exact user/workspace composite keys;
- one ordered transition sequence;
- invitation workspace/recipient/role/digest binding;
- one accepted transition;
- token-hash uniqueness and no plaintext token column;
- closed state/role/policy checks;
- invitation expiry ordering;
- scoped idempotency uniqueness;
- append-only triggers for identities, secret versions, deliveries, and
  histories.

Backfill exactly one active owner membership for each existing workspace,
using `Workspace.owner_id`. Verify no duplicate or orphaned owner.

### Services

- `MembershipService`
- `InvitationService`
- foundational `CollaborationAuthorizationService`

Invitation acceptance:

1. authenticate and require CSRF;
2. hash token and locate exact current secret version;
3. lock invitation and workspace authority rows;
4. verify pending state, expiry, role, workspace, recipient email/user, and
   digest;
5. create membership identity and active transition;
6. append accepted invitation transition;
7. increment authority generation;
8. write Trace/audit/event/outbox;
9. commit once.

### APIs

```text
GET  /workspaces
GET  /workspaces/{workspaceId}/memberships
POST /workspaces/{workspaceId}/invitations
GET  /workspaces/{workspaceId}/invitations
POST /workspaces/{workspaceId}/invitations/{invitationId}/resend
POST /workspaces/{workspaceId}/invitations/{invitationId}/revoke
POST /collaboration-invitations/{invitationId}/accept
POST /collaboration-invitations/{invitationId}/decline
```

No response returns token hashes, raw tokens after the delivery boundary,
unmasked unauthorized emails, permission internals, or foreign-resource
distinctions.

### Acceptance

- Existing and not-yet-registered recipient paths pass.
- Recipient mismatch, token replay/rotation, expiry, revocation, role
  substitution, and cross-workspace acceptance fail closed.
- Duplicate requests converge or conflict on digest.
- Email failure creates no membership or false delivery success.
- Owner backfill and new account owner membership are atomic.
- SQLite migration cycle, append-only guards, offline PostgreSQL DDL, focused
  security tests, and affected backend tests pass.

Implemented limits are 500 active memberships/workspace, 100
workspaces/user, 100 pending invitations/workspace, 7-day default and 30-day
maximum invitation lifetime, 10-minute resend minimum, 5 resends per 24
hours, and list pagination of 50 by default and 100 maximum.

The checkpoint uses owner-only invitation administration as its minimum
authorization boundary. Closed non-owner roles are persisted as ceilings, but
no generalized permission registry, role evaluation, membership lifecycle
administration, sharing, ownership transfer, approval eligibility, or
revocation fencing from 6.2 or later is implemented.

Completion:
`MILESTONE 6.1 COMPLETE LOCALLY — READY FOR 6.2 COLLABORATION ROLES AND PERMISSION AUTHORITY`

## 6.2 — Collaboration Roles and Permission Authority

Status: complete locally on
`milestone-6-2-collaboration-roles-permission-authority-local`.

Implementation handoff:
[MILESTONE_6_2_COLLABORATION_ROLES_PERMISSION_AUTHORITY_HANDOFF.md](MILESTONE_6_2_COLLABORATION_ROLES_PERMISSION_AUTHORITY_HANDOFF.md).

### Scope

- full closed role and permission registries;
- one-role transitions;
- role ceilings and exact permission evaluation;
- approval-authority assignments and revocation;
- Milestone 4 reviewer-eligibility composition;
- membership suspension/restoration/removal;
- authority generations and safe cache/session invalidation signals.

### Persistence

Create and complete migration `20260725_0022` during 6.2. Its direct parent is
`20260725_0021`. It contains only independently valid 6.2 persistence:

- approval-authority assignment identities and transitions;
- append-only reviewer-eligibility evidence;
- database support for authorized active-to-active role transitions by
  superseding the restrictive `0021` guard without modifying `0021`;
- membership/workspace authority-generation indexes and constraints.

It may add only the constraints, indexes, lifecycle and tenant-scope
protections, and audit-supporting fields needed to complete 6.2. It explicitly
excludes typed shares, resource ownership, workspace/resource ownership
transfer, 6.3 authority snapshots and revocation fencing, bulk revocation,
comments, and all later persistence. `0022` is immutable when 6.2 is
committed.

### Services and APIs

- complete `CollaborationAuthorizationService`;
- `ApprovalEligibilityService`;
- membership role/state commands.

```text
POST /workspaces/{workspaceId}/memberships/{membershipId}/role
POST /workspaces/{workspaceId}/memberships/{membershipId}/suspend
POST /workspaces/{workspaceId}/memberships/{membershipId}/restore
POST /workspaces/{workspaceId}/memberships/{membershipId}/remove
```

Routes supply no role defaults beyond explicit closed inputs and never compute
effective permissions.

### Acceptance

- Owner/admin/editor/approver/member/viewer ceilings match the architecture.
- Unknown roles/permissions/states fail closed.
- One membership cannot accumulate hidden role unions.
- Owner/admin do not automatically approve; approver cannot edit or invoke by
  role alone.
- Self-review conflict policies, assignment expiry/revocation, role downgrade,
  approval replay, and cross-scope review fail closed.
- Final owner suspension/removal is denied.
- Existing controlled-agent approval atomicity and digests remain intact.

Completion:
`MILESTONE 6.2 COMPLETE LOCALLY — READY FOR 6.3 RESOURCE SHARING OWNERSHIP AND REVOCATION`

## 6.3 — Resource Sharing, Ownership, and Revocation

### Scope

- typed canvas, canonical-object, workflow, and agent shares;
- `private`, `inherit`, and `workspace_visible` policy;
- workspace and resource ownership transfers;
- explicit unsharing;
- authority snapshots and active-operation fencing;
- safe sharing/ownership APIs.

### Persistence

Create and complete migration `20260725_0023` during 6.3. Its direct parent is
`20260725_0022`. It contains:

- typed resource-share identities and append-only transitions;
- resource-ownership bindings and transitions;
- workspace/resource ownership-transfer identities and transitions;
- collaboration execution-authority snapshots;
- required typed composite FKs, uniqueness, checks, generations, and indexes.

Exactly one target family must be populated. Generic unverified UUID targets
are prohibited. `0023` excludes comments, comment revisions and tombstones,
unrelated collaboration-activity persistence, and all later persistence. It
is immutable when 6.3 is committed.

### Services

- `SharingService`
- `OwnershipTransferService`
- `RevocationFenceService`

Existing owner-only authorization calls migrate to collaboration resolution
one bounded resource family at a time. Historical actor IDs are not rewritten.

### APIs

```text
GET  /workspaces/{workspaceId}/shares
POST /workspaces/{workspaceId}/shares
POST /workspaces/{workspaceId}/shares/{shareId}/revoke
POST /workspaces/{workspaceId}/ownership-transfers
POST /workspaces/{workspaceId}/ownership-transfers/{transferId}/accept
POST /workspaces/{workspaceId}/ownership-transfers/{transferId}/cancel
```

### Acceptance

- Membership alone reveals no canvas.
- Direct child share reveals no siblings and no canvas edit.
- Private resources override inherited access.
- Sharing cannot exceed sharer permission or recipient role ceiling.
- Immutable versions follow their parent identity.
- Read does not imply edit/share/invoke/approve/export.
- Exactly one owner remains through concurrent transfer attempts.
- Role/share/membership revocation fences queued, claimed, provider, retry,
  effect, result, compensation, and export boundaries as specified.
- Foreign target and audience IDs share safe not-found behavior.

Completion:
`MILESTONE 6.3 COMPLETE LOCALLY — READY FOR 6.4 COMMENTS AND COLLABORATION ACTIVITY`

## 6.4 — Comments and Collaboration Activity

### Scope

- comment threads and exact parent resources;
- immutable comment identities;
- append-only revisions, tombstones, moderation, resolution, and reopening;
- closed collaboration event producers;
- audience-aware activity projection;
- optional bounded in-product notification projection only if justified.

### Persistence

Create and complete migration `20260725_0024` during 6.4. Its direct parent is
`20260725_0023`. It contains:

- comment threads;
- comments;
- comment revisions;
- auditable tombstones and bounded reply relationships;
- comment/thread state transitions;
- only minimal event or activity persistence that the checkpoint proves
  cannot use existing systems.

It excludes shared workflow governance, shared agent governance,
collaboration-interface persistence, Advanced Real-Time Collaboration, and
Milestone 7 or later work. `0024` is immutable when 6.4 is committed.

### Services and APIs

- `CommentService`;
- extend existing `DomainEventService`, outbox service, and activity
  projection.

```text
GET  /workspaces/{workspaceId}/resources/{kind}/{id}/comments
POST /workspaces/{workspaceId}/resources/{kind}/{id}/comments
POST /workspaces/{workspaceId}/comments/{commentId}/revisions
POST /workspaces/{workspaceId}/comments/{commentId}/moderate
POST /workspaces/{workspaceId}/comment-threads/{threadId}/resolve
GET  /workspaces/{workspaceId}/collaboration-activity
```

### Acceptance

- Plain text, safe links, size/rate/depth/count bounds, and exact scope pass.
- Cross-scope replies, edit-history rewrite, unauthorized moderation, HTML,
  raw Markdown, unsafe URLs, and identifier probing fail closed.
- Author removal and moderation preserve tombstone evidence.
- Events/outbox commit with authoritative mutations.
- Projection replay and duplicate delivery create one activity item.
- Sensitive invitation/membership/denial activity is audience-filtered.
- Activity never authorizes and notifications do not become messaging.

Completion:
`MILESTONE 6.4 COMPLETE LOCALLY — READY FOR 6.5 SHARED WORKFLOW AND AGENT GOVERNANCE`

Implementation record: migration `20260725_0024`, with direct parent
`20260725_0023`, implements the five scoped append-only comment/thread tables
and database guards. `CommentService` provides exact-scope creation, bounded
replies, author revisions, moderator/author tombstones, and thread
resolve/reopen transitions. `CollaborationActivityService` performs
audience-aware reads over the existing committed domain-event, transactional
outbox, and `activity-v1` projection. No notification persistence, second
feed, frontend component, or 6.5 governance behavior was added.

## 6.5 — Shared Workflow and Agent Governance

### Scope

- shared workflow/agent visibility and immutable-version inspection;
- independent invocation authorization;
- approval eligibility and exact evidence;
- selected-context, citation, Trace, source, and bundle isolation;
- revocation during controlled execution;
- transactional collaboration events and activity.

### Implementation rule

Use existing workflow and Agent Studio `_scope`, `_owned_*`, and
`_authorize_operation` seams. Do not fork workflow, agent, grant, approval,
Trace, event, or activity services.

### Persistence

Create and complete migration `20260725_0025` wholly within 6.5. Its direct
parent is immutable revision `20260725_0024`.

The final design must:

- separate immutable workflow/agent definition-owner scope from invocation
  actor scope;
- preserve `user_id`, or an equivalently clear repository-conventional field,
  as the authenticated invoking user on executions and invocations;
- persist the exact active invoking membership;
- bind tenant, workspace, canvas, parent identity, immutable version,
  definition owner, invoking user, invoking membership, execution, authority
  snapshot, Trace, and audit identities with defensive composite constraints;
- link shared-agent authority evidence to its resulting workflow execution;
- preserve collaboration visibility, invocation permission, current authority
  generation, capability grant, approval, policy, request-idempotency, and
  lifecycle evidence;
- backfill legacy rows with definition owner and invoking user equal to the
  existing recorded user;
- derive invoking membership only from exact historical membership evidence;
- define and test a deterministic fail-closed compatibility rule before
  migration creation when exact historical membership cannot be proved;
- preserve execution identities and append-only Trace, audit, event, outbox,
  activity, retry, cancellation, compensation, export, and publication
  history; and
- pass upgrade, `0025 -> 0024 -> 0025`, SQLite constraints, and PostgreSQL
  offline DDL validation without destructive history loss.

Revision `0025` contains only persistence required for 6.5 shared workflow and
agent governance. It excludes collaboration-interface state, real-time
collaboration, Indexer/production infrastructure, Academy, Catalog, Librarian,
marketplace, reputation, Agent Society, worlds, spatial, federation,
continuity, and all 6.6 or later persistence.

### Acceptance

- Visible workflow/agent cannot be invoked without exact permission,
  capability, grant, approval, context, lifecycle, and digests.
- Invoker remains the actor; creator/owner is not substituted.
- Cross-workspace binding is impossible at service and database boundaries.
- Role/share downgrade invalidates pending activation/approval and fences
  claim/retry/effect/result.
- In-flight provider output is discarded after authority change.
- Separately authorized compensation may finish; otherwise it pauses for new
  authority.
- Citation, source, Trace, and Evidence Bundle reads enforce current access and
  separate export permission.
- Definition ownership and invocation identity remain distinct in persistence,
  services, APIs, authority snapshots, Trace, audit, activity, and retries.
- Revocation and stale-authority checks evaluate the invoker's membership,
  share/visibility basis, permission, generation, grants, approvals, policy,
  and lifecycle rather than substituting definition-owner authority.

Completion:
`MILESTONE 6.5 COMPLETE LOCALLY — READY FOR 6.6 MULTI-WORKSPACE COLLABORATION INTERFACE`

## 6.6 — Multi-Workspace Collaboration Interface

### Scope

- workspace switcher;
- member, invitation, role, transfer, sharing, comment, and activity surfaces;
- workflow/agent sharing and governance;
- suspended/revoked/expired/denied states;
- exact cache partitioning and invalidation;
- accessibility and responsive behavior.

### Frontend rules

- Extend the existing API client, TanStack Query, app router, design tokens,
  dialogs, and components.
- Query keys include session user, workspace, canvas, resource, and authority
  version.
- Logout clears all data; scope change aborts/removes prior queries.
- Never store invitation tokens in URLs, local storage, cache keys, analytics,
  or errors.
- Never calculate roles, permissions, approval eligibility, lifecycle, or
  revocation outcomes in the browser.

### Acceptance

- Direct navigation and refresh enforce server authority.
- Stale responses cannot repopulate revoked data.
- Workspace switch does not flash another workspace's cached content.
- Forms/dialogs are keyboard operable with visible focus, accessible names,
  focus containment/restoration, screen-reader status, reduced motion, and
  narrow layouts.
- Role and risk meaning does not depend on color.
- No raw grant, policy, token, private email, worker, lease, or secret appears.

Completion:
`MILESTONE 6.6 COMPLETE LOCALLY — READY FOR 6.7 FINAL COLLABORATION SECURITY AUDIT`

## 6.7 — Final Collaboration Security Audit

Audit Milestone 4, Milestone 5, and Milestone 6 as one product.

Required gates:

- architecture and registry consistency;
- tenant isolation across database/services/APIs/jobs/frontend;
- identity, creator, owner, membership, role, action, and approval separation;
- invitation, membership, role, share, ownership, comment, approval, workflow,
  agent, event, outbox, activity, Trace, and execution lifecycles;
- transaction/atomicity, idempotency, concurrency, stale generation, failure
  injection, revocation, and compensation;
- complete affected backend/security/migration suites;
- complete frontend/component/API-security tests;
- deterministic Chromium direct-navigation/refresh/keyboard/responsive tests;
- TypeScript, ESLint, Prettier, production build;
- Ruff, strict MyPy, compilation, imports, mappers;
- sole Alembic head and complete upgrade/downgrade/re-upgrade;
- SQLite triggers/constraints and configured PostgreSQL runtime tests where
  available;
- secret, local-path, whitespace, prohibited-scope, hygiene, and Git integrity;
- deterministic demo remains network-free and isolated.

The final audit must not claim PostgreSQL runtime isolation, RLS, production
load, real-time collaboration, or deployment behavior unless actually tested.

Completion:
`MILESTONE 6 COMPLETE LOCALLY — READY FOR MILESTONE 7 PRODUCTION HARDENING ARCHITECTURE`

## Server-owned limits

Implementation starts with the architecture defaults and may lower them after
focused validation:

- 500 active memberships/workspace;
- 100 workspaces/user;
- 100 pending invitations/workspace;
- 7-day invitation default, 30-day maximum;
- 10-minute resend minimum, 5 resends/24 hours/invitation;
- 1 role change/request;
- 50 shares/request, 500 shares/resource, 10,000 shared
  resources/workspace;
- 5,000 code points/comment, 500 comments/thread, depth 4, 30
  comments/minute/membership;
- page defaults/maxima of 50/100;
- 120 workspace switches/minute/user;
- 48-hour transfer default, 7-day maximum;
- 50 bulk revocations/request.

Constants are server-owned. Clients cannot raise them.

## Required test matrix

### Backend and persistence

- membership/invitation/role/share/ownership/comment lifecycle registries;
- authorization composition and unknown-value denial;
- cross-user/workspace/canvas/resource IDOR;
- CSRF and authenticated principal derivation;
- invitation security and enumeration;
- approval/reviewer composition and single-use behavior;
- workflow/agent invocation and selected-context isolation;
- citation, source, Trace, and bundle isolation/export;
- revocation at every execution boundary;
- comments, injection, links, moderation, and tombstones;
- event/outbox/activity audience, replay, and idempotency;
- transaction rollback and no false success;
- deterministic SQLite contention and stale generations;
- migration cycle, constraints, triggers, mappers, PostgreSQL offline DDL;
- configured PostgreSQL locking/isolation tests before production claims.

### Frontend and browser

- API client credentials/CSRF/safe errors;
- query-key partitioning and cache clearing;
- workspace switch, direct navigation, refresh, stale response, and revoked
  access;
- membership/invitation/role/share/transfer/comment/activity states;
- shared workflow/agent visibility versus invocation;
- keyboard, focus, semantics, screen-reader status, reduced motion, and
  responsive layouts;
- no console/hydration/asset errors;
- production build and static analysis.

### Repository

- formatting, typing, lint, compilation, imports, mappers;
- secret/path/whitespace/prohibited-scope scans;
- repository hygiene and Git integrity;
- protected branch/tag and local-only state.

## Deferred roadmap

- Basic presence is optional after core Milestone 6 and is not an acceptance
  criterion.
- Milestone 8.0 completes the commercial SolarPlexus Mobius Core 1.0 product.
- Optional Milestone 8.5 owns Advanced Collaboration after Version 1 is
  released and stable.
- Milestone 7 retains the deterministic Indexer and production hardening.
- Milestone 9 begins the separate SolarPlexus Mobius Society product line and
  retains the governed Librarian.
- Milestones 10–13 begin Mobius Worlds, Spatial, Federation, and Continuity.
- Later products depend on stable, versioned Core authority, Trace, audit, and
  service contracts; they are not unfinished Core checkpoints.
- Milestones 7–13 are not started by this plan.

See
[`MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md`](MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md).
