# Milestone 7 PostgreSQL Trigger-Function Compatibility Amendment

Date: 2026-07-27

Status: documentation amendment complete locally; trigger-function correction
not implemented; Milestone 7.2 not started

## Authoritative documentation baseline

This amendment was created from:

- branch:
  `milestone-7-postgresql-historical-migration-corrections-final-local`;
- commit: `faa49cad75e7343f0dd7b20aef71ad25c16e318d`;
- commit message:
  `Authorize PostgreSQL UUID null typing in migration 0023`;
- parent: `495664668271214cfd84d905d70b93cb47d6869b`;
- Alembic sole head: `20260725_0025`;
- working tree: clean;
- upstream: none.

The local commit containing this document, with message
`Authorize PostgreSQL trigger-function correction for migrations 0023 and 0024`,
is the authoritative baseline for the next combined implementation checkpoint.
Its exact SHA is recorded in the final handoff because a commit cannot contain
its own SHA.

This amendment authorizes exactly one additional exceptional historical
PostgreSQL correction: replace four references to a nonexistent trigger
function in migrations `20260725_0023` and `20260725_0024` with the existing
function that implements their required deny-all mutation behavior. It does
not implement the correction, modify a migration, apply preserved work,
activate a migration hash, create a later migration, or relax migration
integrity generally.

## Preserved implementation and recovery state

The most complete combined implementation attempt remains outside the working
tree:

- stash object:
  `d50c7020f9b9ce6add83f10d0b443510ccd33ba3`;
- stash message:
  `postgresql-historical-corrections-blocked-by-0023-security-trigger-function`;
- recovery patch:
  `postgresql-historical-corrections-blocked-by-0023-security-trigger-function-faa49ca.patch`;
- recovery patch size: `119612` bytes;
- recovery patch SHA-256:
  `2e6726045825fa61d0302d2bc5ac59efca3aa1c1143982aea681998e380b2fca`;
- recovery manifest:
  `postgresql-historical-corrections-blocked-by-0023-security-trigger-function-faa49ca.manifest.txt`;
- recovery manifest SHA-256:
  `a39859f68b50cebf70bd1e35982b29a499d9c7e0e47cfb3c17871a7cc1758ab8`.

Earlier recovery evidence remains intact:

- blocked parser/backfill stash:
  `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`;
- original migration `0005`/runner stash:
  `71b384404468fbfa6326a951ef063e99c9e11652`;
- original recovery patch:
  `postgresql-0005-runner-provisional-7303386.patch`;
- original recovery patch SHA-256:
  `f165bdd10df4cb95112985396c8ea143c609bf883596ffecd04ae9f9cb9c6f46`;
- original recovery manifest:
  `postgresql-0005-runner-provisional-7303386.manifest.txt`;
- original recovery manifest SHA-256:
  `330c23163a96ba22f16d57710253e4081e93c2b9a9e9bc3f3a5a16ea540c7d11`.

All three stash objects remained present, unchanged, unapplied, and undropped
during this checkpoint. Neither patch nor either manifest was modified. No
credential, connection string, or absolute recovery path is recorded here.

## Verified environment and failure

The failure was proved previously with:

- Ubuntu 24.04.4 under WSL 2;
- PostgreSQL 17.10;
- pgvector 0.8.5;
- disposable loopback-only databases;
- credentials stored outside the repository;
- no cloud or remote database;
- no production data or deployment.

After the separately authorized parser and UUID-null corrections allowed the
live chain to reach trigger installation, migration `0022 -> 0023` failed
while creating:

`trg_collaboration_resources_mutation_blocked`

PostgreSQL reported:

```text
UndefinedFunctionError: function
reject_controlled_agent_security_mutation() does not exist
```

This is a historical function-name compatibility defect. It is not a
PostgreSQL installation, pgvector, WSL, migration-runner, UUID, check-parser,
Indexer, or Milestone 7.2 defect.

No live database probe was required for this documentation checkpoint.
PostgreSQL was returned to its stopped state after preflight inspection.

## Exact affected revisions and ancestry

| Revision        | File                                                     | Parent          | Child           |
| --------------- | -------------------------------------------------------- | --------------- | --------------- |
| `20260725_0023` | `20260725_0023_resource_sharing_ownership_revocation.py` | `20260725_0022` | `20260725_0024` |
| `20260725_0024` | `20260725_0024_comments_collaboration_activity.py`       | `20260725_0023` | `20260725_0025` |

Each file contains two affected helpers:

- `_protect()`;
- `_protect_domain_events()`.

Exactly four textual calls reference the missing function: one in each helper
in each migration. No revision identifier, parent, child, helper signature,
trigger name, table list, or operation set is ambiguous.

## Existing function identity and behavior

Migration
`apps/api/alembic/versions/20260721_0007_controlled_agent_persistence.py`
creates:

```sql
CREATE FUNCTION reject_controlled_agent_mutation()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'controlled-agent records are append-only';
END;
$$ LANGUAGE plpgsql
```

Its exact contract is:

- name: `reject_controlled_agent_mutation`;
- signature: zero arguments;
- return type: `trigger`;
- language: `plpgsql`;
- behavior: unconditionally raise the exact append-only exception;
- returned row: none, because every invocation fails;
- tenant, table, role, and operation branching: none.

The function would reject any trigger operation bound to it. Migration `0007`
and the affected migrations bind this contract only to
`BEFORE UPDATE OR DELETE`. They deliberately permit valid insertion of a new
append-only record and prohibit later update or deletion. This amendment does
not authorize an insert-blocking trigger.

Migration `0007` installs the existing function for ten controlled-agent
append-only tables. Migrations `0008`, `0009`, `0012`, and `0015` reuse it for
later equivalent update/delete guards. Migration `0007` owns its lifecycle:
its downgrade drops the protected tables before dropping the function. No
later migration drops, replaces, overloads, or changes it.

The application model layer independently applies its shared
`_reject_controlled_agent_mutation` listener to the thirteen collaboration
models introduced by migrations `0023` and `0024`, for both update and delete.
That confirms that these tables use the same append-only behavior rather than
a distinct security-specific mutation policy.

## Complete historical function-name search

A complete search through sole head `20260725_0025` established:

- `reject_controlled_agent_security_mutation()`:
  - four references;
  - zero definitions;
  - zero replacements;
  - zero overloads;
  - zero downgrade drops;
- `reject_controlled_agent_mutation()`:
  - one definition in migration `0007`;
  - one owning downgrade drop in migration `0007`;
  - trigger use in migrations `0007`, `0008`, `0009`, `0012`, and `0015`;
- the separately named
  `reject_agent_rollback_evidence_mutation()`,
  `reject_agent_rollback_approval_mutation()`,
  `reject_agent_rollback_result_mutation()`,
  `reject_agent_execution_authority_mutation()`, and
  `reject_domain_event_outbox_identity_mutation()` functions in migrations
  `0013` through `0015` and `0017` are revision-owned, have explicit matching
  create/drop lifecycles, and implement table-owned append-only or narrower
  authority/identity protection; none defines or implies the missing
  security-named function;
- dynamic `reject_<table>_mutation()` helpers in migrations `0016` through
  `0022` create, invoke, and drop matching table-owned names;
- migration `0025` neither defines the missing name nor repairs or duplicates
  the defect;
- no other reachable migration through `0025` contains the same
  undefined-function defect.

The missing security-named function first appears as an invocation in
`0023`. Repository history contains no implementation, deletion, rename
boundary, separate message contract, or distinct lifecycle for it.

## Exact reachable triggers and protected tables

### Migration `20260725_0023`

Its PostgreSQL `upgrade()` invokes `_protect()` for these eight tables:

| Protected table                                | Trigger                                                             |
| ---------------------------------------------- | ------------------------------------------------------------------- |
| `collaboration_resources`                      | `trg_collaboration_resources_mutation_blocked`                      |
| `collaboration_resource_ownership_transitions` | `trg_collaboration_resource_ownership_transitions_mutation_blocked` |
| `collaboration_resource_shares`                | `trg_collaboration_resource_shares_mutation_blocked`                |
| `collaboration_resource_share_transitions`     | `trg_collaboration_resource_share_transitions_mutation_blocked`     |
| `collaboration_ownership_transfers`            | `trg_collaboration_ownership_transfers_mutation_blocked`            |
| `collaboration_ownership_transfer_transitions` | `trg_collaboration_ownership_transfer_transitions_mutation_blocked` |
| `collaboration_authority_snapshots`            | `trg_collaboration_authority_snapshots_mutation_blocked`            |
| `collaboration_revocation_fences`              | `trg_collaboration_revocation_fences_mutation_blocked`              |

### Migration `20260725_0024`

Its PostgreSQL `upgrade()` invokes `_protect()` for these five tables:

| Protected table                            | Trigger                                                         |
| ------------------------------------------ | --------------------------------------------------------------- |
| `collaboration_comment_threads`            | `trg_collaboration_comment_threads_mutation_blocked`            |
| `collaboration_comment_thread_transitions` | `trg_collaboration_comment_thread_transitions_mutation_blocked` |
| `collaboration_comments`                   | `trg_collaboration_comments_mutation_blocked`                   |
| `collaboration_comment_revisions`          | `trg_collaboration_comment_revisions_mutation_blocked`          |
| `collaboration_comment_transitions`        | `trg_collaboration_comment_transitions_mutation_blocked`        |

Every trigger above is `BEFORE UPDATE OR DELETE FOR EACH ROW`. The first
reachable failure is the first `0023` trigger, so none of the later twelve can
be created until the name defect is corrected.

Both downgrades call `_unprotect()` before dropping their tables.
`_unprotect()` drops only the table trigger. Neither migration creates, owns,
or drops a shared mutation-rejection function. That lifecycle requires reuse
of an earlier-owned function.

## Domain-event helper reachability

Each affected migration also contains a PostgreSQL branch in
`_protect_domain_events()` that would create:

- table: `domain_events`;
- trigger: `trg_domain_events_mutation_blocked`;
- operations: `BEFORE UPDATE OR DELETE`.

Those two branches contain the other two invalid references. They are latent
in the normal PostgreSQL chain: each helper is currently called only after a
SQLite table recreation, and then returns through its SQLite branch.

PostgreSQL already receives `trg_domain_events_mutation_blocked` from
migration `20260725_0017`. That existing trigger remains bound to its
table-owned `reject_domain_events_mutation()` function. The future correction
must not drop, duplicate, or rebind that normal-chain trigger.

The two latent strings are still inside the affected historical helpers and
must be corrected so no invalid function reference remains. Validation must
distinguish:

- live creation of the thirteen reachable new-table triggers;
- preservation of the existing `0017` domain-event trigger and function;
- static and isolated disposable-transaction proof that each corrected
  `_protect_domain_events()` PostgreSQL branch resolves if invoked.

## Selected resolution: correct the four references

**Resolution A is authorized exclusively.**

The future combined implementation may replace exactly four occurrences of:

`reject_controlled_agent_security_mutation()`

with:

`reject_controlled_agent_mutation()`

The authorized occurrences are:

1. migration `0023`, `_protect()`;
2. migration `0023`, `_protect_domain_events()`;
3. migration `0024`, `_protect()`;
4. migration `0024`, `_protect_domain_events()`.

This resolution is proved because the existing function:

- has the exact zero-argument trigger signature required by the calls;
- always fails hard and therefore implements the complete deny-all mutation
  behavior;
- is already present before revision `0023`;
- remains present through revision `0025`;
- is already reused by later historical append-only triggers;
- has no table-specific or controlled-agent-only decision branch;
- matches the shared ORM mutation contract applied to the affected
  collaboration models; and
- has an existing ownership and downgrade lifecycle compatible with
  trigger-only cleanup in `0023` and `0024`.

Trigger names, protected tables, update/delete coverage, transaction failure,
append-only semantics, and the existing function lifecycle remain unchanged.

## Rejected resolution: define a distinct function

**Resolution B is rejected and not authorized.**

Repository evidence provides no distinct:

- behavior;
- exception contract;
- signature;
- creation boundary;
- owner migration;
- trigger family;
- downgrade cleanup;
- overload;
- policy rule; or
- application-layer mutation behavior

for `reject_controlled_agent_security_mutation()`.

Defining it would duplicate an unconditional deny-all function, invent a new
historical lifecycle, and introduce ambiguity over whether `0023`, `0024`, or
another migration owns its removal. An alias or compatibility shim would
retain two equivalent functions with unclear ownership. The four references
are therefore unimplemented name drift, not evidence of a separate security
policy.

## Narrow authorized correction boundary

The future combined implementation may modify only the two affected migration
files and only the four function-name references listed above under this
amendment.

It must preserve:

- revision identifiers, parents, children, and linear order;
- all trigger names and affected table coverage;
- `BEFORE UPDATE OR DELETE FOR EACH ROW`;
- valid insert behavior;
- hard exception and transaction rollback behavior;
- append-only, authority, ownership, tenant, audit, Trace, event, outbox, and
  evidence contracts;
- existing rows and all valid data;
- SQLite branches and behavior;
- the migration `0007` function definition and lifecycle;
- the migration `0017` domain-event function and trigger;
- existing downgrade refusal and trigger-drop behavior.

The correction adds no new function, trigger, table, column, constraint,
index, revision, service, API, runtime setting, dependency, or product
feature.

## Explicitly prohibited changes

The future implementation must not:

- define, alias, or retain
  `reject_controlled_agent_security_mutation()`;
- modify migration `0007` or its existing function;
- modify migration `0017` or rebind its normal domain-event trigger;
- remove, rename, disable, defer, or weaken a mutation-blocking trigger;
- allow UPDATE or DELETE of an affected append-only record, or prohibit an
  otherwise-valid INSERT;
- add INSERT to the affected trigger operations;
- replace hard failure with logging or a permissive return;
- change the exception body or swallow the database exception;
- change trigger timing, row/statement scope, or table coverage;
- change an unrelated trigger function or validation guard;
- use `CASCADE`;
- drop protected rows or alter protected table schemas;
- weaken tenant, ownership, authority, audit, Trace, or evidence scope;
- change the SQLite branch;
- modify a migration outside `0023` and `0024`;
- skip or stamp a migration;
- create a replacement revision or parallel bootstrap;
- create migration `0026`, `0027`, or `0028`;
- activate an intermediate migration hash;
- start Indexer persistence, Milestone 7.2, deployment, Milestone 8, or the
  governed Librarian.

## Relationship to prior amendments

This amendment preserves without broadening:

- [migration `0005` dialect compatibility](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md);
- [migrations `0023` and `0024` check-parser compatibility](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md);
- [migration `0023` UUID-null typing](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md);
- guarded migration-runner rollback before advisory unlock;
- advisory-lock exclusion and release;
- original migration-exception precedence;
- PostgreSQL URL and credential redaction;
- focused PostgreSQL and SQLite tests required by those corrections.

The next checkpoint restores the most complete stash, reviews every change
against its own amendment, adds only the four name replacements authorized
here, and validates all corrections together. This amendment does not approve
the preserved implementation as complete.

## Migration hash exception policy

The protected pre-correction hashes remain:

- `0023`: `01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`;
- `0024`: `fb4e8e264a5a73f2ab543d9cb0fc920ace4fbefb`.

The future combined checkpoint must:

1. calculate one final active Git blob hash for migration `0023`;
2. record that its content includes the approved parser, UUID-null, and
   trigger-reference corrections;
3. calculate one final active Git blob hash for migration `0024`;
4. record that its content includes the approved parser and trigger-reference
   corrections;
5. preserve both original hashes permanently;
6. record the exact SHAs of all applicable amendments and the implementation
   commit;
7. record the date, reason, exact scope, deployment boundary, and validation
   evidence;
8. activate hashes only after every mandatory test passes;
9. reject parser-only, UUID-only, trigger-only, provisional, or otherwise
   intermediate active hashes;
10. keep every unrelated migration hash unchanged; and
11. make any later unapproved edit fail validation.

No hash changes or becomes active in this documentation checkpoint.

## Required future PostgreSQL function validation

Before creating an affected trigger, live PostgreSQL tests must prove:

- `to_regprocedure('reject_controlled_agent_mutation()')` resolves;
- exactly one zero-argument function with that name exists;
- its return type is `trigger`;
- its language is `plpgsql`;
- its body contains the exact unconditional append-only exception;
- no ambiguous overload exists;
- `reject_controlled_agent_security_mutation()` does not exist;
- the existing function remains owned by migration `0007`;
- downgrade and re-upgrade create no duplicate or orphan function.

After each upgrade, inspect PostgreSQL catalogs and prove every one of the
thirteen reachable trigger function OIDs resolves to the existing
`reject_controlled_agent_mutation()` function.

The normal chain must separately prove that the existing
`trg_domain_events_mutation_blocked` remains present and bound to
`reject_domain_events_mutation()` from migration `0017`.

For each migration module, an isolated disposable PostgreSQL transaction must
temporarily remove the existing domain-event trigger, invoke the corrected
module-local `_protect_domain_events()` PostgreSQL branch, prove the trigger
can be created and resolves to `reject_controlled_agent_mutation()`, prove
UPDATE and DELETE both fail with the established exception without changing
the valid test row or leaving a partial transaction, and roll the entire probe
back. Static and captured-SQL assertions must additionally prove that no
security-named reference remains in either file.

## Required mutation-blocking validation

For every one of the thirteen reachable protected tables:

1. insert a valid scoped row through the established schema contract;
2. verify the insert succeeds;
3. attempt a direct update and require the exact existing append-only
   exception;
4. roll back the failed transaction boundary;
5. attempt a direct delete and require the same exception;
6. roll back the failed transaction boundary;
7. prove row count and exact row values remain unchanged;
8. prove user, workspace, canvas, resource, ownership, and evidence scope
   remain unchanged;
9. prove no partial transaction, audit state, or side effect survives;
10. restart the disposable PostgreSQL service instance and repeat
    trigger/function identity plus UPDATE/DELETE rejection and rollback checks
    for all thirteen reachable new-table triggers and the preserved
    `domain_events` guard.

Tests must not require INSERT rejection. They must prove only the established
update/delete contract.

## Required migration and cross-correction cycles

Live PostgreSQL 17 with pgvector must prove:

- `0022 -> 0023`;
- `0023 -> 0022`;
- re-upgrade to `0023`;
- `0023 -> 0024`;
- `0024 -> 0023`;
- re-upgrade to `0024`;
- empty schema through `0025`;
- `0025 -> 0024 -> 0025`;
- all thirteen affected triggers after each applicable upgrade;
- no orphan or duplicate mutation function after downgrade;
- deterministic schema, rows, trigger identities, and function identities.

The combined checkpoint must validate together:

- migration `0005` dialect-safe correction;
- migration `0023` parser correction;
- migration `0023` UUID-null typing;
- migration `0023` trigger-reference correction;
- migration `0024` parser correction;
- migration `0024` trigger-reference correction;
- guarded migration-runner rollback before cleanup;
- advisory-lock exclusion and release;
- original-exception preservation;
- cleanup-failure precedence;
- transaction and connection closure;
- URL and credential redaction.

## Required SQLite regression

SQLite must prove:

- no PostgreSQL function name or cast enters its migration branch;
- clean migration through `0025`;
- `0004 -> 0005 -> 0004 -> 0005`;
- `0022 -> 0023 -> 0022 -> 0023`;
- `0023 -> 0024 -> 0023 -> 0024`;
- `0025 -> 0024 -> 0025`;
- valid inserts and rejected updates/deletes for affected append-only tables;
- deterministic demo reset, check, and startup smoke;
- no table, trigger, schema, row, tenant, ownership, or evidence regression.

## Required full combined regression

After focused PostgreSQL and SQLite gates pass, run all applicable:

- trigger-function and affected-trigger tests;
- parser, UUID-backfill, migration, runner, lock, and redaction tests;
- full live PostgreSQL marker suite;
- Milestone 7.1 runtime tests;
- backend, security, and integration suites;
- strict Python typing, formatting, lint, compilation, imports, and mapping;
- frontend tests, type checking, lint, formatting, and production build;
- browser smoke tests;
- deterministic demo validation;
- SQLite and PostgreSQL migration-chain validation;
- Alembic sole-head and parent-chain validation;
- migration-hash validation;
- repository hygiene, secret, local-path, generated-artifact, dependency,
  lockfile, runtime-configuration, CI, deployment, whitespace, and diff
  checks;
- Git object integrity and protected-reference verification.

A mandatory PostgreSQL skip is not a pass.

## Milestone 7.2 restart gate

Migration `0026` and Milestone 7.2 remain prohibited until:

1. this amendment is committed locally;
2. a new implementation branch starts from that exact commit;
3. stash `d50c7020f9b9ce6add83f10d0b443510ccd33ba3`
   is applied, not popped;
4. both earlier stashes and all external recovery materials remain intact;
5. every restored change is reviewed against its separate amendment;
6. exactly the four function references authorized here are corrected;
7. the thirteen reachable triggers are created and bind the existing
   function;
8. both latent domain-event helper references are corrected while the normal
   `0017` domain-event trigger remains intact;
9. update/delete rejection and transaction rollback are proved for every
   affected table;
10. the clean PostgreSQL chain reaches `0025`;
11. every required PostgreSQL and SQLite downgrade/re-upgrade cycle passes;
12. parser, UUID, runner, lock, exception, cleanup, closure, and redaction
    tests pass;
13. final migration exception hashes are recorded and activated;
14. every unrelated migration hash remains unchanged;
15. the complete repository regression passes;
16. implementation and evidence commits are completed locally;
17. the final tree is clean with no upstream;
18. no critical or high-severity migration defect remains; and
19. migrations `0026`, `0027`, and `0028` remain absent until all gates pass.

Only the final combined correction commit may become the authoritative
baseline for restarting checkpoint 7.2.

## Documentation-only confirmation

This checkpoint changes documentation only. It does not modify migration
`0005`, `0023`, or `0024`; production code; tests; dependencies; lockfiles;
runtime configuration; CI; deployment implementation; or recovery materials.
No stash was applied, popped, changed, or dropped. No migration hash was
activated. Migrations `0026`–`0028` remain absent, and Milestone 7.2 remains
unstarted.
