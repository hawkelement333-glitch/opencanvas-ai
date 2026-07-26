# Milestone 6.3 Resource Sharing, Ownership, and Revocation Handoff

Status: complete locally; Milestone 6.4 not started

## Completed boundary

Milestone 6.3 adds closed, typed sharing for canvases, canonical objects,
workflow identities, and agent identities. Shares name either the workspace or
one exact active membership and grant only `view`, `contribute`, or `manage`.
Workflow and agent versions follow their parent identity and cannot be shared
independently. Sharing does not grant invocation, approval, export, controlled
write, or Milestone 4 authority.

Resource identity and current ownership are server-derived from exact user,
workspace, and canvas scope. Visibility is closed to `private`, `inherit`, or
`workspace_visible`. Direct child grants and parent-canvas inheritance are
evaluated independently; visual adjacency and sibling placement grant nothing.

Workspace and resource ownership changes use pending, accepted transfer
records. Acceptance is atomic, requires the exact active recipient membership,
preserves one workspace owner, and records the former owner role. Revocation,
visibility changes, membership changes, and accepted ownership transfers
advance the workspace authority generation.

## Persistence and service surface

Migration `20260725_0023` adds eight scoped tables:

- `collaboration_resources`;
- `collaboration_resource_ownership_transitions`;
- `collaboration_resource_shares`;
- `collaboration_resource_share_transitions`;
- `collaboration_ownership_transfers`;
- `collaboration_ownership_transfer_transitions`;
- `collaboration_authority_snapshots`;
- `collaboration_revocation_fences`.

Composite foreign keys bind typed resources to their exact workspace and, for
workflows and agents, exact user and canvas. Closed checks reject unknown
resource, audience, access, visibility, owner, transfer, lifecycle, permission,
boundary, and scope values. Unique identities prevent duplicate share
audiences and duplicate transition sequences. Registration triggers cover
new canvases, canonical objects, workflow identities, and agent identities.
Append-only and lifecycle triggers reject update, delete, non-successor, and
non-monotonic evidence.

The thin collaboration API now exposes:

- paginated share inspection and bounded batch creation;
- bounded single or bulk share revocation;
- typed visibility changes;
- workspace or resource transfer requests;
- exact-recipient accept and reject decisions;
- requester cancellation.

`SharingService`, `ResourceRegistryService`, `OwnershipTransferService`, and
`RevocationFenceService` centralize scope resolution, permission evaluation,
idempotency, limits, inheritance, ownership, transfer, generation, evidence,
and stale-authority enforcement. Routes do not construct authority.

## Evidence and stale-work rejection

Migration `20260725_0023`, directly after `20260725_0022`, owns:

- typed collaboration resources and immutable ownership transitions;
- typed shares and immutable share transitions;
- ownership-transfer identities and immutable decisions;
- immutable authority snapshots and revocation fences;
- deterministic backfill and registration guards for existing and new
  resources;
- closed event, audit, and idempotency vocabularies;
- append-only lifecycle enforcement.

The authority snapshot records the exact membership, role, permission,
resource, share, and generation used at a controlled boundary. The revocation
fence rejects a stale claim, service/tool call, retry, effect, compensation,
export, publication, share decision, or ownership decision after authority has
changed. This is execution evidence, not private model reasoning.

Every successful sharing or ownership mutation emits an append-only
collaboration audit fact, Trace evidence, a domain event, and transactional
outbox work in the same transaction. Failed authorization and failed
transactions leave no partial share, ownership, generation, audit, Trace,
event, or outbox state.

The existing generic outbox projector produces activity entries after delivery.
No parallel event, outbox, activity, Trace, audit, or cache system was added.
The server-owned workspace authority generation is the cache partition and
invalidation fence; stale frontend or worker state is never authority.

Controlled-agent execution captures authority when the collaboration
foundation is present and revalidates before claim, lease continuation, and
publication. Controlled workflows capture authority at execution creation and
revalidate before claim, service work, controlled effects, compensation, and
publication. A generation change caused by share revocation, ownership
transfer, membership/role change, or workspace lifecycle change therefore
rejects later work. Visibility still does not grant workflow or agent
invocation; Milestone 4 policy/grant/approval and the existing owner-scoped
workflow rules remain required.

## Validation record

- Complete backend suite: `506 passed`, `1 skipped`; the skip is the
  environment-gated live PostgreSQL test. Warnings were 35 known Python 3.12
  SQLite datetime-adapter deprecations and one existing Starlette status-name
  deprecation.
- Explicit security suite: `37 passed`.
- Focused 6.3 sharing/ownership/revocation scenario: passed, including exact
  replay, stale-snapshot rejection, expired-transfer rejection and replacement,
  concurrent resource-transfer acceptance, former-owner denial, visibility
  update by the eligible new owner, and atomic workspace transfer.
- Final collaboration, migration, and domain-event matrix: `28 passed`; fresh upgrade,
  `0023 -> 0022 -> 0023`, append-only guards, sole head, `0024` absence, and
  PostgreSQL offline DDL all passed.
- Controlled workflow, retry, recovery, cancellation, deadline, and stale
  result suites: the established matrix passed `76` tests and the final expanded
  affected matrix passed `94` tests.
- Frontend: ESLint passed, TypeScript passed, `66` tests passed, and the
  production Next.js build passed.
- Chromium: `6 passed`, `2 skipped`; the skips are the local-harness
  real-PostgreSQL scenarios.
- Ruff formatting/lint, strict mypy over 81 source files, compilation, imports,
  ORM mapper validation, Prettier, diff/whitespace, repository hygiene and
  built-in secret scan over 336 source files, local-path leakage,
  prohibited-scope, dependency/lockfile, and Git object checks passed.
- The bundled `pnpm` wrapper reproduced the documented ignored-build policy
  for `sharp` and `unrs-resolver`. Dependency approval policy was not changed;
  equivalent locked executables were run directly and passed.

Migration hashes remain unchanged:

- `20260725_0021`:
  `3baeb7d4deeb5dbf13b230de49ea6a787ce3a0c4`;
- `20260725_0022`:
  `d4a3bfc1bd32b3df9a886645fba318a51d2ed3a0`.

## Compatibility boundary

Existing Milestone 4 and 5 policy, grant, controlled-execution, workflow, and
Agent Studio contracts remain authoritative. Milestone 6.3 does not implement
comments, collaboration activity UI, shared workflow invocation, shared agent
invocation, advanced real-time collaboration, or cross-workspace authority.
There is no 6.3 frontend surface: API behavior is complete and the existing UI
is unchanged. Share and transfer expiration is enforced at authoritative
decision time; no speculative scheduler or distributed cache was added.
Revision `20260725_0024` remains absent.

Milestone 6.4 may begin from this checkpoint and must preserve migration
`20260725_0023`, its direct parent, append-only evidence, exact scope, and
revocation-generation semantics.

MILESTONE 6.3 COMPLETE LOCALLY — READY FOR 6.4 COMMENTS AND COLLABORATION ACTIVITY
