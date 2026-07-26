# Milestone 6 Progress — Core Multi-Workspace Collaboration

Last updated: 2026-07-26

Branch: `milestone-6-7-final-collaboration-security-audit-local`

Baseline: `01a38526320560d54033bed510b0f15a7e77eea7`

Status: Milestone 6 architecture and checkpoints 6.1–6.7 complete locally

| Checkpoint                                       | Status           | Dependency                        |
| ------------------------------------------------ | ---------------- | --------------------------------- |
| Architecture                                     | Complete locally | Milestone 5 and roadmap amendment |
| 6.1 Workspace Membership and Invitations         | Complete locally | Architecture                      |
| 6.2 Collaboration Roles and Permission Authority | Complete locally | 6.1                               |
| 6.3 Resource Sharing, Ownership, and Revocation  | Complete locally | 6.1–6.2                           |
| 6.4 Comments and Collaboration Activity          | Complete locally | 6.1–6.3                           |
| 6.5 Shared Workflow and Agent Governance         | Complete locally | 6.1–6.4 and Milestones 4–5        |
| 6.6 Multi-Workspace Collaboration Interface      | Complete locally | 6.1–6.5                           |
| 6.7 Final Collaboration Security Audit           | Complete locally | 6.1–6.6                           |

## Architecture decisions

- Extend current owner-only authorization seams with one central
  collaboration resolver.
- Keep Milestone 4 capability, grant, risk, approval, digest, and revocation
  checks authoritative.
- Use one closed role per membership; no role unions or free-text
  permissions.
- Role is a ceiling. Exact typed resource ownership/share/inheritance is also
  required.
- Keep invitation pre-acceptance evidence separate from active membership so
  every membership has an exact user.
- Preserve one workspace owner with accepted transfer and no orphan state.
- Keep creator, owner, membership, action authority, and approval authority
  distinct.
- Extend Milestone 4 approval with reviewer-eligibility evidence rather than
  create another approval system.
- Fence revocation with monotonic workspace, membership, share, and approval
  generations.
- Use typed shares for canvas, canonical resources, workflows, and agents.
- Treat immutable versions as children of the shared identity; never share
  them independently.
- Keep source/Bundle export separate from read access.
- Store comments as escaped plain text with immutable identities,
  append-only revisions, and tombstones.
- Extend existing domain events, outbox, and activity; add no second feed.
- Preserve PostgreSQL RLS and real-time collaboration as future adapter
  options, not current claims or schema.

## Closed role model

The initial registry is owner, administrator, editor, approver, member, and
viewer. A membership has exactly one current role. Owner controls transfer;
administrator manages bounded membership/sharing; editor changes explicitly
accessible resources; approver reviews only exact assigned classes; member
participates only where shared; viewer is read-only.

No role bypasses Milestone 4 or independently supplies resource visibility,
invocation, approval, export, or controlled-effect authority.

## Persistence

- `20260725_0021`: complete locally; memberships, invitation
  identity/state/secret/delivery, idempotency, collaboration audit,
  owner-membership backfill, and workspace authority version.
- `20260725_0022`: complete locally for 6.2 only; active-to-active role-transition
  support, approval-authority/approver-eligibility persistence, and exclusive
  6.2 constraints, indexes, tenant scope, lifecycle, and audit support. Direct
  parent: `20260725_0021`.
- `20260725_0023`: complete for 6.3 only; typed shares, resource ownership,
  ownership transfer, authority snapshots, and revocation fencing. Direct
  parent: `20260725_0022`.
- `20260725_0024`: complete locally for 6.4 only; exact comment-thread and
  comment identities, append-only revisions and lifecycle transitions,
  auditable tombstones, bounded replies, closed registries, scope/sequence
  guards, and indexes. Direct parent: `20260725_0023`.
- `20260725_0025`: complete locally for 6.5 only; separates immutable
  definition ownership from the authenticated invoking user and exact active
  membership, reinforces composite scope, and deterministically backfills
  provable legacy invocation authority. Direct parent: `20260725_0024`.

Each migration is completed within its owning checkpoint and remains
immutable after commit. Later changes use the next unused revision. Alembic
has one sole head: `20260725_0025`. Checkpoints 6.6 and 6.7 have no migration
assigned.

## Scope boundaries

Milestone 6 core includes memberships, invitations, roles, sharing, ownership,
revocation, comments, activity, shared workflow/agent governance, frontend
management, and final tenant-security audit.

Basic presence is optional stretch scope and not required.

Milestone 8.0 completes and releases the commercial SolarPlexus Mobius Core
1.0 product. Optional Milestone 8.5, SolarPlexus Mobius Core 1.5 — Advanced
Collaboration, follows only after Version 1 is stable. No cursors, detailed
presence, simultaneous editing, CRDT, OT, offline merge, reconnect
reconciliation, or distributed real-time infrastructure is designed for
implementation in Milestone 6.

Milestone 7 retains Production Hardening and the deterministic Indexer.
Milestone 9 begins the separate SolarPlexus Mobius Society product line and
retains the governed Librarian. Milestones 10–13 begin Mobius Worlds,
Spatial, Federation, and Continuity. They build on stable, versioned Core
contracts and are not required for Mobius Core completion. Milestones 7–13
remain unstarted.

See
[`MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md`](MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md).

## Current implementation state

Checkpoint 6.1 adds immutable membership and invitation identities,
append-only lifecycle, secret, delivery, idempotency, audit, Trace, event,
outbox, and activity evidence; deterministic owner backfill; workspace
authority versions; central membership/invitation services; and the approved
authenticated APIs.

Invitation credentials use cryptographically random bearer values and persist
only keyed HMAC digests. Recipients bind to the exact authenticated normalized
email/user. Resend rotates the current secret. Acceptance is one-time,
idempotent, concurrency-safe, and atomic with membership creation, authority
generation, audit, Trace, domain event, and outbox evidence. Safe errors do not
distinguish foreign workspaces, invitations, recipients, or credentials.

Owner membership is created atomically for new workspaces and deterministically
backfilled for existing workspaces. Active membership resolution now allows a
user to list their exact workspaces without rewriting historical owner/creator
identity.

Validation includes 496 passing backend tests, 1 skipped PostgreSQL-only test,
36 deprecation warnings, focused security/concurrency/failure-injection tests,
SQLite upgrade/downgrade/re-upgrade, PostgreSQL offline DDL, production
typing, lint, formatting, compilation, frontend regression, production build,
and repository hygiene checks. Exact commands and results are recorded in the
6.1 handoff.

Checkpoint 6.2 adds the closed six-role and 36-permission registries, explicit
role ceilings, a centralized deny-by-default collaboration evaluator,
authorized append-only active role changes and membership
suspension/restoration/removal, and bounded approval-authority assignment,
replacement, revocation, and exact reviewer evaluation. The existing 6.1
membership and invitation administration paths now use formal action checks.

Every authority mutation advances the workspace authority generation exactly
once in the same transaction and records append-only audit, Trace, domain
event, transactional outbox, and activity-projectable evidence. Exact replay
returns the prior result without a second mutation or generation increment.
Owner membership and owner role remain protected. Accepted workspace transfer
preserves exactly one owner and accepted resource transfer preserves exact
membership ownership.

Typed sharing, resource ownership, accepted ownership transfer, authority
snapshots, and revocation fencing are complete locally.

Checkpoint 6.4 adds exact-resource comment threads, immutable comment
identities, append-only revisions, author and moderator tombstones, bounded
four-level replies, thread resolution/reopening, and safe list/history APIs.
Creation is capped at 5,000 code points, 500 comments per thread, and 30
comments per membership per minute. Pages default to 50 and stop at 100.
All authority is server-derived through the central collaboration evaluator
and current typed-resource visibility; stale generation, removed membership,
hidden scope, foreign parent, stale revision, and unauthorized moderation
fail closed.

Comment changes atomically create audit, Trace, domain-event, and transactional
outbox evidence. Collaboration activity reads the existing delivered
`activity-v1` projection, rechecks current visibility, filters by exact
resource/event type, and exposes no comment text or private authority facts.
Focused tests cover concurrent duplicate creation, concurrent edit conflict,
idempotent replay, depth bounds, revision immutability, tombstone history,
moderation, visibility-only viewers, removed membership, activity replay and
pagination, cross-workspace denial, unsafe text, and injected transaction
rollback. No collaboration UI, workflow/agent governance, real-time
collaboration, Indexer, or Librarian work was added.

Final 6.4 validation includes 510 passing backend tests with 1 skipped
PostgreSQL-only test, 38 passing security tests, 22 passing integration tests,
66 passing frontend tests, 6 passing Chromium smoke tests with 2 expected
real-service skips, strict typing, lint, formatting, production build,
SQLite migration cycling, PostgreSQL offline DDL, mapper/import/compilation,
demo, hygiene, diff, protected-reference, and prohibited-scope checks. Exact
commands, warnings, and environment notes are recorded in the 6.4 handoff.

Checkpoint 6.5 adds centralized shared invocation governance for workflow and
agent identities. Safe list/read paths evaluate current typed visibility;
invocation separately requires the closed `workflow.invoke` or `agent.invoke`
permission. Immutable versions inherit their parent identity and cannot be
shared independently. Execution rows preserve definition owner,
authenticated invoker, exact active membership, immutable version, authority
snapshot, workspace, canvas, request identity, Trace, and execution linkage.

The workflow and agent services retain all Milestone 4 capability, approval,
risk, lifecycle, selected-context, retry, cancellation, compensation, export,
publication, and stale-result fences. Revocation checks use the invoker's
captured collaboration authority, so definition ownership cannot keep an
execution valid after the invoker loses access. Successful invocations create
bounded audit evidence linked to the existing domain event, outbox, activity,
and Trace systems. Shared inspection omits other users' private invocation,
evaluation, proposal, activation, binding, capability, approval, and authority
details.

Final 6.5 validation includes 518 passing backend tests with 1 skipped
PostgreSQL-runtime test, 38 passing security tests, 22 passing integration
tests, 66 passing frontend tests, and 6 passing Chromium smoke tests with 2
real-service skips. Strict typing, focused lint/formatting, compilation,
121-table mapper configuration, SQLite migration cycling, PostgreSQL offline
DDL, production build, and repository hygiene pass. Exact results and the
pre-existing repository-wide Ruff baseline differences are recorded in the
6.5 handoff.

Checkpoint 6.6 adds the bounded collaboration console at `/collaboration`.
Authorized users can switch server-returned workspaces, inspect current
identity/membership/role/lifecycle/authority state, administer permitted
memberships, invitations, reviewer eligibility, shares, visibility, and
ownership transfers, participate in bounded plain-text comment threads, read
the existing `activity-v1` projection, and discover or invoke shared workflows
and agents only when the server confirms invocation availability.

TanStack Query keys include authenticated user, workspace, authority
generation, resource/canvas, and automation identity. Workspace changes and
revocation cancel and remove prior-scope queries, reset resource-bound state,
and require a fresh server collaboration context. Closed Zod registries reject
malformed or unknown authority, role, share, lifecycle, visibility, activity,
workflow, and agent response values.

Minimal backend corrections expose only already-approved 6.1–6.5 operations:
active-member workspace and shared-canvas discovery, bounded collaboration
context, approval-authority and transfer listing, visible resource ownership,
and server-confirmed shared workflow/agent definition owner, visibility basis,
and invocation availability. A full backend regression found and corrected
one tenant-isolation response defect: a foreign workspace canvas-list request
now returns non-enumerating 404 rather than an empty 200 response.

Milestone 6.6 creates no migration and leaves revisions `20260725_0021`
through `20260725_0025` immutable. The sole head remains
`20260725_0025`. Advanced Real-Time Collaboration, Milestone 7 Indexer and
production infrastructure, and Mobius Society/Librarian scope remain
unstarted.

Final 6.6 validation includes 518 passing backend tests with 1 skipped
PostgreSQL-runtime test and 61 dependency deprecation warnings, 74 passing
frontend tests across 17 files, and 8 passing Chromium tests with 2 expected
real-service skips. Production Ruff, strict MyPy across 83 source files,
TypeScript, ESLint, Prettier, compilation/import, 121-table mapper
configuration, production build, SQLite migration cycling, PostgreSQL offline
DDL, deterministic demo, 355-file repository hygiene, and the focused
accessibility/responsive assertions pass.

Checkpoint 6.7 audited all 14 integrated collaboration areas and found two
concrete defects:

1. The collaboration console's visible-canvas query key omitted authenticated
   user scope. A focused regression reproduced the missing key family. The key
   now includes user, workspace, authority generation, and canvas-list
   identity, preventing same-workspace cache reuse across authenticated users.
2. Four historical Milestone 4 command examples contained a local absolute
   user path. They now use `<repository-root>`, and the established hygiene
   validator rejects Windows, macOS, or Linux user-home paths.

No backend, database, API, migration, authority, Trace, audit, event, outbox,
activity, workflow, agent, or controlled-execution defect was proved. Final
validation passed 518 backend tests with 1 expected PostgreSQL-runtime skip
and 61 dependency warnings; 38 security tests with 481 deselections; 22
integration tests with 1 warning; 31 focused Milestone 6 tests with 35
dependency warnings; 74 frontend tests across 17 files; and 8 Chromium tests
with 2 expected real-service skips. Strict typing, lint, formatting,
compilation, imports, 121 ORM tables, production build, migration cycle,
PostgreSQL offline DDL, deterministic demo, and 357-file hygiene passed.

Migrations `0021`–`0025` retain their immutable blob hashes, no migration
`0026` exists, and the sole head remains `20260725_0025`.

Next authorized work:
`MILESTONE 7 — PRODUCTION HARDENING ARCHITECTURE`
