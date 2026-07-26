# Milestone 6 Migration Boundary Amendment

Date: 2026-07-25

Branch: `milestone-6-migration-boundary-amendment-local`

Starting commit: `b4b67d5206a862997bb962d868f785b029febeda`

Status: documentation amendment complete locally; fulfilled by completed
Milestone 6.2 migration `20260725_0022`

Completion cross-reference: Milestone 6.2 subsequently completed the amended
boundary in migration `20260725_0022`; see
[MILESTONE_6_2_COLLABORATION_ROLES_PERMISSION_AUTHORITY_HANDOFF.md](MILESTONE_6_2_COLLABORATION_ROLES_PERMISSION_AUTHORITY_HANDOFF.md).
Milestone 6.3 subsequently completed its separately allocated direct child
`20260725_0023`; see
[MILESTONE_6_3_RESOURCE_SHARING_OWNERSHIP_REVOCATION_HANDOFF.md](MILESTONE_6_3_RESOURCE_SHARING_OWNERSHIP_REVOCATION_HANDOFF.md).
Milestone 6.4 subsequently completed its separately allocated direct child
`20260725_0024`; see
[MILESTONE_6_4_COMMENTS_COLLABORATION_ACTIVITY_HANDOFF.md](MILESTONE_6_4_COMMENTS_COLLABORATION_ACTIVITY_HANDOFF.md).
Milestone 6.5 later proved that shared invocation requires a distinct
definition-owner and invoking-actor persistence boundary. The
documentation-only
[Milestone 6.5 invocation-identity amendment](MILESTONE_6_5_INVOCATION_IDENTITY_MIGRATION_AMENDMENT.md)
therefore allocates direct child `20260725_0025`; the migration and
implementation are not created.

## Original contradiction

The approved architecture assigned roles, approval authority, typed sharing,
ownership, authority snapshots, and revocation fencing to one combined
`20260725_0022` migration. The implementation plan then instructed 6.2 to
begin that migration and 6.3 to complete it.

That allocation was incompatible with the repository's immutable-migration
contract. Committing a partial `0022` in 6.2 would require 6.3 to rewrite a
committed migration. Avoiding a migration in 6.2 was also unsafe: migration
`0021` permits active membership transitions only to `suspended` or `removed`,
so it cannot persist an authorized active-to-active role change, and
collaboration approval-authority assignments require durable persistence.

Implementation therefore stopped before branch creation, production changes,
tests, or migrations. This amendment resolves only that documented boundary.

## Permanent migration rule

- A migration is created and completed within one owning checkpoint.
- No checkpoint commits a partial migration for a later checkpoint to
  rewrite.
- A committed migration remains immutable.
- A later correction or extension uses the next unused revision.
- Every migration has one direct parent.
- The repository retains one Alembic head.
- Documentation never describes a migration as beginning in one checkpoint
  and being completed in another.

This allocation changes no collaboration, tenant-isolation, ownership,
approval, revocation, append-only, Trace, event, outbox, audit, or security
invariant.

## `20260725_0022` — Milestone 6.2 only

Direct parent: `20260725_0021`

Complete scope:

- collaboration approval-authority or approver-eligibility assignment
  persistence required by 6.2;
- database support for authorized active-to-active membership role
  transitions;
- replacement or supersession of the restrictive `0021` transition guard
  through `0022`, without modifying `0021`;
- constraints, indexes, lifecycle protections, tenant-scope protections, and
  audit-supporting fields required exclusively by 6.2;
- any other persistence proved necessary to make the closed role and
  permission-authority system independently complete.

Excluded:

- typed resource, canvas, note, document, workflow, or agent shares;
- resource ownership;
- workspace or resource ownership-transfer requests and transfers;
- authority snapshots and revocation fencing assigned to 6.3;
- bulk revocation;
- comments, revisions, tombstones, and all later persistence.

`0022` must be complete and immutable when 6.2 is committed.

## `20260725_0023` — Milestone 6.3 only

Direct parent: `20260725_0022`

Complete scope:

- typed, revocable resource shares;
- resource-ownership persistence;
- workspace ownership-transfer requests and acceptance;
- approved resource ownership-transfer behavior;
- authority snapshots required by sharing and ownership;
- monotonic authority-generation or revocation-fencing persistence assigned
  to 6.3;
- sharing/ownership/revocation constraints, indexes, lifecycle protections,
  and tenant-scope protections.

Excluded:

- comments, revisions, and tombstones;
- unrelated collaboration-activity persistence;
- all 6.4 or later persistence.

`0023` must be complete and immutable when 6.3 is committed.

## `20260725_0024` — Milestone 6.4 only

Direct parent: `20260725_0023`

Complete scope:

- comment threads;
- append-only comment revisions and history;
- auditable tombstones;
- bounded reply relationships;
- only minimal collaboration event or activity persistence that 6.4 proves
  cannot use the existing systems.

Excluded:

- shared workflow governance;
- shared agent governance;
- collaboration-interface persistence;
- Advanced Real-Time Collaboration;
- Milestone 7 or later work.

`0024` must be complete and immutable when 6.4 is committed.

## `20260725_0025` — Milestone 6.5 only

Direct parent: `20260725_0024`

Complete planned scope:

- separate immutable workflow and agent definition-owner scope from invocation
  actor scope;
- preserve the authenticated invoking user on workflow executions and bounded
  agent invocations;
- persist the exact active invoking membership;
- preserve exact workspace, canvas, parent identity, immutable version,
  definition owner, invoker, membership, execution, authority snapshot,
  Trace, and audit scope;
- bind collaboration visibility, invocation permission, authority generation,
  capability, approval, policy, request-idempotency, lifecycle, and revocation
  evidence;
- link shared-agent authority evidence to the resulting workflow execution;
- deterministically backfill legacy owner-only rows without changing existing
  execution identities or append-only histories; and
- include only constraints, indexes, portability guards, and compatibility
  behavior required to complete 6.5 independently.

Before the migration is created, 6.5 must specify and test a deterministic
fail-closed compatibility rule for any historical row whose exact invoking
membership cannot be derived from authoritative workspace-membership
evidence. It must not invent an actor or rewrite historical Trace/audit
meaning.

Excluded:

- multi-workspace frontend or collaboration-administration UI persistence;
- Advanced Real-Time Collaboration, presence, cursors, CRDT/OT, and offline
  merge state;
- Indexer or managed production infrastructure;
- Academy, Catalog, Librarian, marketplace, reputation, or Agent Society;
- worlds, spatial intelligence, federation, or continuity; and
- all Milestone 6.6 or later persistence.

`0025` must be created, completed, validated, and committed wholly within 6.5
and remains immutable afterward.

## Checkpoint alignment

- 6.1 -> `20260725_0021` — complete
- 6.2 -> `20260725_0022` — complete and immutable
- 6.3 -> `20260725_0023` — complete and immutable
- 6.4 -> `20260725_0024` — complete and immutable
- 6.5 -> `20260725_0025` — planned, exclusively allocated, not created
- 6.6 -> no migration currently assigned
- 6.7 -> no migration currently assigned

If 6.6, 6.7, or a later correction proves new persistence necessary, it uses
the next unused revision rather than modifying committed migrations `0021`
through `0025`.

## Historical unchanged implementation state

Migration `20260725_0021` remains unchanged and is the sole Alembic head. No
migration was created. No production code, test, dependency, configuration,
CI, deployment, frontend, backend, or API implementation changed. Milestone
6.2, Milestone 6.3, and all later checkpoints remain unstarted.

This paragraph records the original amendment checkpoint. It is superseded for
current implementation status by completed immutable migrations `0022`–`0024`
and the planned, uncreated `0025` allocation above.

Advanced Real-Time Collaboration remains after Milestone 8. Milestone 7
retains the deterministic Indexer, and Milestone 9 retains the governed
Librarian and Agent Society.

## Historical 6.2 restart baseline

Milestone 6.2 may restart only from the committed local amendment branch and
SHA recorded by its final handoff, with:

- a clean working tree;
- no upstream and no remote operation;
- sole Alembic head `20260725_0021`;
- migrations `20260725_0022`, `20260725_0023`, and `20260725_0024` absent;
- protected references unchanged; and
- `20260725_0022` owned exclusively and completely by Milestone 6.2.
