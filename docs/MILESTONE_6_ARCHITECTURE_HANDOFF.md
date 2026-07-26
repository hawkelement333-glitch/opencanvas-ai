# Milestone 6 Architecture Handoff — Core Multi-Workspace Collaboration

Date: 2026-07-25

Branch: `milestone-6-multi-workspace-collaboration-architecture-local`

Starting commit: `01a38526320560d54033bed510b0f15a7e77eea7`

Commit: `Design Milestone 6 collaboration architecture`

Status: architecture complete locally; implementation not started

Next checkpoint: 6.1 — Workspace Membership and Invitations

## Outcome

The repository now has a complete implementation-ready architecture for core
multi-workspace collaboration. It extends the existing owner-scoped service
seams, Milestone 4 controlled-agent authority contracts, and Milestone 5
graph, retrieval, workflow, Trace, event, activity, Dynamic Universe, and Agent
Studio contracts. It does not create a parallel authority, approval, workflow,
agent, event, or activity system.

This pass changes documentation only. It creates no model, migration, schema,
service, API, test, fixture, component, dependency, configuration, CI, or
deployment behavior. Migration `20260725_0021` does not exist, Alembic remains
at sole head `20260725_0020`, and Milestone 6.1 has not started.

## Documents

- `docs/MILESTONE_6_ARCHITECTURE.md` is the normative architecture.
- `docs/MILESTONE_6_IMPLEMENTATION_PLAN.md` defines checkpoints 6.1–6.7 and
  their acceptance boundaries.
- `docs/MILESTONE_6_PROGRESS.md` records architecture completion and every
  implementation checkpoint as not started.
- This handoff records the decisions, repository fit, validation boundary, and
  local-only state.
- `README.md` identifies architecture completion and 6.1 as the next
  authorized checkpoint.

## Repository-grounded foundations

The design was derived from the repository rather than imposed as a parallel
framework:

- authenticated identity is the server-derived `Principal` backed by the
  existing session model;
- mutations retain the existing CSRF boundary;
- `Workspace.owner_id` and current owner-only workspace, canvas, document, and
  Trace checks are the authorization seams to evolve;
- Milestone 4 capabilities, grants, risk, approval, digest, revocation,
  execution, effect, compensation, audit, and Trace contracts remain
  authoritative;
- Milestone 5 canonical resources, immutable versions, selected context,
  citations, workflows, agents, Evidence Bundles, domain events, outbox, and
  activity keep their existing identities and histories;
- workflows already expose scoped definition/version service seams, and Agent
  Studio already exposes centralized operation authorization and scoped
  identity/version lookup seams;
- the frontend continues to use the existing API client, TanStack Query, and
  scoped query invalidation rather than adding another state framework.

## Decided collaboration contract

### Authority composition

Every operation evaluates authenticated identity, active membership, the
membership's one closed role, explicit resource visibility, exact
collaboration permission, exact resource scope, and lifecycle/revocation
state. Controlled operations then also evaluate the existing Milestone 4
capability, risk, grant, approval, immutable digests, and execution lifecycle.

Role, membership, ownership, sharing, graph adjacency, UI selection, Trace,
events, prior success, or model output never supplies authority by itself.
Unknown registry or lifecycle values fail closed.

### Roles and permissions

One membership has exactly one role from the versioned registry: `owner`,
`administrator`, `editor`, `approver`, `member`, or `viewer`. Multi-role unions
and a generic superuser are rejected.

The collaboration-permission registry is closed and separate from controlled
agent capabilities. It covers workspace, membership, invitation, role,
ownership-transfer, canvas, resource, comment, workflow, agent, approval, and
activity actions. A role is only a permission ceiling. Resource access and any
required Milestone 4 authority must still be proven independently. No
free-text permission is accepted.

### Membership and invitation lifecycle

Invitations own pre-acceptance states; a membership is created only when an
authenticated user safely accepts. This preserves an exact non-null user on
every membership while the combined admission lifecycle still represents
invited, pending, active, suspended, removed, expired, and declined outcomes.
Historical membership evidence remains append only.

Invitation secrets are one-time, bounded, workspace- and intended-role-bound,
and stored only as nonrecoverable digests. Recipient matching, replay
protection, revocation, bounded resend, duplicate handling, no enumeration,
and deterministic no-email local tests are required. Existing users accept
while authenticated. A not-yet-registered recipient completes registration
and identity verification before the same authenticated acceptance service is
allowed to activate membership.

### Visibility and sharing

Workspace membership does not expose every canvas. A canvas is private,
inherits an explicit workspace-visible policy, or is covered by a typed share.
Typed shares may target a workspace audience or an active membership and use
closed `view`, `contribute`, or `manage` access. They never target another
workspace and never create capability, approval, invocation, or export
authority.

Canvases, canonical objects, workflow identities, and agent identities are
shareable through real scoped foreign keys. Immutable workflow and agent
versions follow their authoritative identity and are not independently
shareable. Retrieval passages, citations, Trace records, and immutable
evidence follow the authorization of their authoritative parent. Source and
Evidence Bundle export remains a separate permission and policy decision.

Private resources remain private inside a shared workspace. Sharing changes
are versioned, audited, emitted through the existing event/outbox path, and
fenced by server-owned authority generations.

### Ownership and approval

Creator identity is immutable history. Workspace ownership, resource
ownership, membership, role, action authority, approval authority, and any
future billing ownership remain separate.

A workspace has exactly one owner. Transfer requires an eligible active
recipient, one live request, recipient acceptance, expiry/cancellation
handling, an atomic owner change, and retention of at least one owner. The old
owner becomes administrator by default unless a future closed policy says
otherwise. Resource transfer follows typed ownership and cannot cross the
workspace.

The collaboration `approver` role does not replace Milestone 4 approval.
Reviewer eligibility is recorded against the existing approval request using
exact workspace, action, resource, risk, version/digest, expiry, revocation,
single-use, and conflict-of-interest evidence. Owners and administrators are
not universal approvers, and an ineligible requester cannot self-approve.

### Revocation and running work

Workspace, membership, share, and approval generations change monotonically.
Services and workers revalidate their captured authority snapshot before
claim, provider call, retry, effect, completion, compensation, export, and
result publication.

Revoked users cannot start new authoritative work. A stale provider response
is discarded before commit. Uncommitted work is canceled or fenced. Committed
effects remain historical facts; already-authorized compensation may finish
only when its compensation authority is still valid, otherwise the execution
pauses for explicit reauthorization. Pending approvals and activation
requests are invalidated when their reviewer or requester authority changes.
Historical events, comments, approvals, effects, Trace, audit, and evidence
are never rewritten.

### Workflows, agents, comments, and activity

Shared workflow and agent visibility does not permit activation or invocation.
Each use rechecks active membership, role ceiling, typed access, lifecycle,
capability, grant, approval, exact user/workspace/canvas/resource scope, and
context/plan/request/version digests. Core Milestone 6 permits no
cross-workspace binding.

Comments are bounded plain text attached to exact scoped parent resources.
They retain immutable author and creation identity, append-only revisions,
closed lifecycle transitions, and moderation/author-removal tombstones rather
than hard deletion. Safe links, size/depth limits, identifier-scope checks,
and injection and mention-abuse defenses are mandatory.

Collaboration events extend the existing domain-event, transactional outbox,
and activity projections. Activity is historical product evidence;
notifications, if later justified, are a bounded derived in-product
projection, not a second messaging platform.

## Tenant and frontend invariants

All collaboration-sensitive persistence and operations bind exact user,
workspace, canvas, resource, membership, lifecycle, role/permission, and
authority generation. Composite foreign keys, server-derived scope, scoped
repository queries, centralized service authorization, allowlisted
serialization, scoped events/outbox/activity/Trace/audit, and bound
idempotency digests provide defense in depth.

The frontend partitions query keys by authenticated session/user, workspace,
canvas, and authority version where applicable. Workspace or authority changes
cancel stale requests, clear inaccessible cache entries, and refetch
authoritative state. Direct navigation and refresh remain server-authorized.
Mutations use CSRF. Interfaces are paginated, keyboard accessible, responsive,
reduced-motion compatible, and do not expose invitation tokens, raw grants,
policy internals, or unauthorized recipient email.

PostgreSQL row-level security remains a future defense-in-depth option, not a
current isolation claim. SQLite tests cannot prove PostgreSQL runtime
isolation.

## Planned implementation

The documentation-only migration-boundary amendment supersedes the original
combined allocation with checkpoint-owned immutable revisions:

1. `20260725_0021`: complete 6.1 membership/invitation persistence; direct
   parent `20260725_0020`;
2. `20260725_0022`: complete 6.2-only role-transition and
   approval-authority/approver-eligibility persistence; direct parent
   `20260725_0021`;
3. `20260725_0023`: complete 6.3-only typed sharing, resource ownership,
   ownership transfer, authority snapshot, and revocation-fencing
   persistence; direct parent `20260725_0022`;
4. `20260725_0024`: complete 6.4-only comment history, tombstone, bounded
   reply, and minimally necessary event/activity persistence; direct parent
   `20260725_0023`.

Migrations `0022`, `0023`, and `0024` are planned and not created. Checkpoints
6.5–6.7 have no assigned migration. A migration is completed within one
checkpoint, remains immutable after commit, and is never completed by a later
checkpoint. Later corrections use the next unused revision while preserving
one Alembic head.

Each future migration requires exact scope columns, composite keys, closed
checks, uniqueness and live-request constraints, immutable versus mutable
field documentation, required indexes, SQLite enforcement, PostgreSQL offline
DDL validation, and upgrade/downgrade/re-upgrade coverage.

The service plan centralizes membership resolution, permission evaluation,
invitations, membership lifecycle, role changes, ownership transfer, typed
sharing, reviewer eligibility, comments, activity, invalidation, and
revocation fencing. Routes remain thin and expose only bounded authenticated
human actions. Browser APIs never expose raw grants, raw policy mutation,
worker/outbox/lease controls, arbitrary workflow/agent authority, or
cross-workspace bindings.

## Formal checkpoints

1. 6.1 — Workspace Membership and Invitations
2. 6.2 — Collaboration Roles and Permission Authority
3. 6.3 — Resource Sharing, Ownership, and Revocation
4. 6.4 — Comments and Collaboration Activity
5. 6.5 — Shared Workflow and Agent Governance
6. 6.6 — Multi-Workspace Collaboration Interface
7. 6.7 — Final Collaboration Security Audit

The future test matrix covers lifecycle registries, invitations, role and
approval authority, sharing, ownership, revocation during active work,
workflow/agent isolation, selected context, citations and bundles, comments,
events/outbox/activity, authentication and CSRF, cross-user/workspace/canvas
IDOR, caching, idempotency, deterministic concurrency, failure injection,
migration cycles, SQLite constraints, PostgreSQL offline DDL, frontend,
browser, accessibility, responsive behavior, builds, static analysis, hygiene,
and Git integrity.

## Bounded defaults

The architecture proposes server-owned implementation-time maxima for
memberships, pending invitations, invitation lifetime and resend frequency,
role/share batches, total shares, comment length/count/depth, membership,
invitation, activity, and notification pages, workspace switching,
ownership-transfer lifetime, and bulk revocation. They are defaults subject to
repository validation during the owning checkpoint and cannot be weakened by
clients.

## Roadmap boundary

Basic presence is optional stretch scope after core Milestone 6 and is not an
acceptance requirement. Advanced Real-Time Collaboration—including live
cursors, detailed presence, simultaneous editing, CRDT/OT synchronization,
offline merge, reconnect reconciliation, and distributed real-time
infrastructure—remains a separate phase after the initial Milestone 8
controlled release. Only abstract future adapter seams are preserved; no
algorithm, field, dependency, or runtime is selected.

Milestone 7 retains Production Hardening and the deterministic Indexer.
Milestone 9 retains the governed Librarian and Agent Society. Collaboration
scope and isolation provide their future authority foundation without moving
either into Milestone 6. Milestones 7–13 remain not started.

## Validation record

The architecture closeout validates:

- documentation formatting;
- diff and whitespace correctness;
- roadmap, role, permission, and lifecycle terminology consistency;
- documentation-only prohibited-scope boundaries;
- unchanged production code, tests, migrations, dependencies,
  configuration, CI, and deployment files;
- no local-path or secret-like-material leakage;
- repository hygiene and Git object integrity;
- Alembic sole head `20260725_0020`;
- clean final tree, no upstream, and unchanged protected references; and
- no remote operation.

No backend, frontend, browser, network, or migration-cycle suites are run
because the authorized change is architecture documentation only.

## Local Git boundary

The architecture branch was created directly from
`01a38526320560d54033bed510b0f15a7e77eea7` without moving the completed
Milestone 5 branch. All work remains local. No upstream is configured. No
push, pull, fetch, sync, pull request, remote branch/tag change, upload,
publication, deployment, release, GitHub Actions change, repository-setting
change, or other remote operation is authorized or performed.

Milestone 6 architecture is complete locally. Milestone 6 implementation is
not started. Milestone 6.1 is the next authorized checkpoint.
