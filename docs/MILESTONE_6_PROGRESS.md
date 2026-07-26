# Milestone 6 Progress — Core Multi-Workspace Collaboration

Last updated: 2026-07-25

Branch: `milestone-6-migration-boundary-amendment-local`

Baseline: `01a38526320560d54033bed510b0f15a7e77eea7`

Status: checkpoint 6.1 complete locally; migration boundaries clarified; ready for 6.2 architecture-preserving implementation

| Checkpoint                                       | Status           | Dependency                        |
| ------------------------------------------------ | ---------------- | --------------------------------- |
| Architecture                                     | Complete locally | Milestone 5 and roadmap amendment |
| 6.1 Workspace Membership and Invitations         | Complete locally | Architecture                      |
| 6.2 Collaboration Roles and Permission Authority | Not started      | 6.1                               |
| 6.3 Resource Sharing, Ownership, and Revocation  | Not started      | 6.1–6.2                           |
| 6.4 Comments and Collaboration Activity          | Not started      | 6.1–6.3                           |
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
- `20260725_0022`: planned for 6.2 only; active-to-active role-transition
  support, approval-authority/approver-eligibility persistence, and exclusive
  6.2 constraints, indexes, tenant scope, lifecycle, and audit support. Direct
  parent: `20260725_0021`.
- `20260725_0023`: planned for 6.3 only; typed shares, resource ownership,
  ownership transfer, authority snapshots, and revocation fencing. Direct
  parent: `20260725_0022`.
- `20260725_0024`: planned for 6.4 only; comment threads, append-only
  revisions/history, auditable tombstones, bounded replies, and only minimal
  new event/activity persistence proved necessary. Direct parent:
  `20260725_0023`.

Each migration is completed within its owning checkpoint and remains
immutable after commit. Later changes use the next unused revision. Alembic
has one sole head: `20260725_0021`. Migrations `20260725_0022`,
`20260725_0023`, and `20260725_0024` do not exist. Checkpoints 6.5, 6.6, and
6.7 have no migration assigned.

## Scope boundaries

Milestone 6 core includes memberships, invitations, roles, sharing, ownership,
revocation, comments, activity, shared workflow/agent governance, frontend
management, and final tenant-security audit.

Basic presence is optional stretch scope and not required.

Advanced Real-Time Collaboration remains after the initial Milestone 8
release. No cursors, detailed presence, simultaneous editing, CRDT, OT,
offline merge, reconnect reconciliation, or distributed real-time
infrastructure is designed for implementation here.

Milestone 7 retains Production Hardening and the deterministic Indexer.
Milestone 9 retains the governed Librarian and Agent Society. Milestones 7–13
remain unstarted.

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

Milestone 6.2 remains unstarted. No role-permission engine, role changes,
membership suspension/restoration/removal, sharing, ownership transfer,
approval eligibility, comments, collaboration UI, real-time collaboration,
Indexer, or Librarian work was added.

Next authorized implementation start:
`MILESTONE 6.2 — COLLABORATION ROLES AND PERMISSION AUTHORITY`
