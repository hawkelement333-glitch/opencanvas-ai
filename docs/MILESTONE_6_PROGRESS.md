# Milestone 6 Progress — Core Multi-Workspace Collaboration

Last updated: 2026-07-26

Branch: `milestone-6-4-comments-collaboration-activity-local`

Baseline: `01a38526320560d54033bed510b0f15a7e77eea7`

Status: checkpoints 6.1–6.4 complete locally; ready for 6.5

| Checkpoint                                       | Status           | Dependency                        |
| ------------------------------------------------ | ---------------- | --------------------------------- |
| Architecture                                     | Complete locally | Milestone 5 and roadmap amendment |
| 6.1 Workspace Membership and Invitations         | Complete locally | Architecture                      |
| 6.2 Collaboration Roles and Permission Authority | Complete locally | 6.1                               |
| 6.3 Resource Sharing, Ownership, and Revocation  | Complete locally | 6.1–6.2                           |
| 6.4 Comments and Collaboration Activity          | Complete locally | 6.1–6.3                           |
| 6.5 Shared Workflow and Agent Governance         | Not started      | 6.1–6.4 and Milestones 4–5        |
| 6.6 Multi-Workspace Collaboration Interface      | Not started      | 6.1–6.5                           |
| 6.7 Final Collaboration Security Audit           | Not started      | 6.1–6.6                           |

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

Each migration is completed within its owning checkpoint and remains
immutable after commit. Later changes use the next unused revision. Alembic
has one sole head: `20260725_0024`. Checkpoints 6.5, 6.6, and 6.7 have no
migration assigned.

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

Next authorized implementation start:
`MILESTONE 6.5 — SHARED WORKFLOW AND AGENT GOVERNANCE`
