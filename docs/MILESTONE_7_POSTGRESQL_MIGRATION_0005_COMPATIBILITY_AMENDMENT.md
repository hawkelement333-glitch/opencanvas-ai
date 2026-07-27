# Milestone 7 PostgreSQL Migration 0005 Compatibility Amendment

Date: 2026-07-26

Status: documentation amendment complete locally; focused correction not
implemented; Milestone 7.2 not started

Authoritative correction baseline:

- branch:
  `milestone-7-postgresql-migration-0005-compatibility-amendment-local`;
- parent commit: `62f8f981eb4580d8f174dac44faaf746112891e7`;
- parent commit message:
  `Add production runtime and managed PostgreSQL foundation`;
- Alembic sole head: `20260725_0025`;
- affected historical revision: `20260718_0005`;
- direct parent: `20260717_0004`;
- direct child: `20260721_0006`;
- pre-correction Git blob hash:
  `ac5bf41ae5cfefa785006c7eef2a730233e46da9`;
- planned `20260726_0026`: absent.

This amendment authorizes a focused correction checkpoint. It does not
implement the correction, change a migration, change production code, or
relax migration integrity generally.

## Verified environment and failure

The failure was reproduced against an isolated local environment:

- Ubuntu 24.04.4 under WSL 2;
- PostgreSQL 17.10;
- pgvector 0.8.5;
- UTF-8 database encoding;
- SCRAM credentials;
- separate non-superuser migration and application test roles;
- loopback-only PostgreSQL listener at `127.0.0.1:55432`;
- no cloud database, remote provider, production data, or production
  deployment.

A clean live PostgreSQL upgrade reaches revision `20260718_0005` and fails
when `20260718_0005_productization_bridge.py` enters:

```python
op.batch_alter_table("workspaces", recreate="always")
```

Alembic attempts:

```sql
ALTER TABLE workspaces DROP CONSTRAINT workspaces_pkey
```

PostgreSQL rejects the operation because
`canonical_objects_workspace_id_fkey` depends on the `workspaces_pkey` index.
Revision `0004` creates `canonical_objects.workspace_id` as a restrictive
foreign key to `workspaces.id` before revision `0005` attempts to recreate the
referenced table.

This is a live PostgreSQL migration defect. It is not a WSL, PostgreSQL
installation, pgvector, offline-generation, managed-provider, or Milestone
7.2 defect.

The intended `0005` schema remains valid: existing workspace rows receive the
system migration owner, `owner_id` becomes non-null and references `users.id`,
and `settings_payload` and `deleted_at` are added without changing workspace
identity or the existing canonical-object relationship.

## Why an exceptional correction is required

A later migration cannot repair the problem because a fresh PostgreSQL
database cannot complete `0005` and therefore cannot reach that later
revision. Stamping `0005` as applied would omit required schema and data work.
Dropping dependent constraints externally would make the migration result
dependent on undocumented operator steps.

A separate bootstrap lineage is rejected because it would create parallel
schema histories, ambiguous release artifacts, divergent downgrade behavior,
and a second source of truth for migration integrity. The repository has not
claimed a production deployment of this chain, so no deployed-data procedure
is invented here.

The smallest safe action is one transparent, hash-ledgered correction to the
implementation of revision `0005`, preserving its identity, ancestry,
semantic result, and cross-dialect behavior.

## Narrowly authorized migration exception

The focused correction checkpoint may modify exactly:

`apps/api/alembic/versions/20260718_0005_productization_bridge.py`

It may change only the implementation needed for revision `0005` to produce
the same intended schema and data transition safely on supported dialects.
The semantic requirement is:

- retain table recreation only where required and safe, including the
  established SQLite compatibility path;
- on PostgreSQL, alter the existing table without replacing its primary-key
  structure or invalidating dependent foreign keys;
- preserve every workspace row and stable workspace identifier;
- make `owner_id` non-null after its deterministic backfill;
- create the intended owner foreign key;
- preserve the intended `settings_payload` and `deleted_at` columns;
- preserve equivalent upgrade and downgrade outcomes;
- preserve the final schema expected by all later migrations and ORM models.

The correction checkpoint must inspect the whole `0005` migration for other
unconditional `recreate="always"` operations that produce the same dialect
risk. It may correct such operations only inside this same file, only when
required to make the existing `0005` semantic transition executable, and
only with equivalent SQLite and PostgreSQL outcomes. This does not authorize
a schema redesign or unrelated cleanup.

The correction must not change:

- revision `20260718_0005`;
- direct parent `20260717_0004`;
- direct child or migration order;
- intended final schema or domain meaning;
- workspace, tenant, ownership, or authorization boundaries;
- historical business facts;
- any later migration;
- production feature behavior.

## Explicitly prohibited migration changes

The focused correction must not:

- redesign or rename the `workspaces` table;
- create another revision for the same historical operation;
- use `CASCADE`;
- drop data;
- weaken, skip, or disable foreign keys, checks, unique constraints, or
  triggers;
- remove dependent foreign keys without restoring and proving them safely;
- skip `0005` on PostgreSQL;
- stamp the revision without equivalent schema and data work;
- special-case only the current fixture;
- create a parallel bootstrap or production migration history;
- modify a migration other than `0005`;
- include migration `0026` or any Milestone 7.2 state.

## Guarded migration-runner correction

The focused correction checkpoint is separately authorized to modify only the
guarded migration-runner implementation and its focused tests as needed to
preserve the primary database exception.

The correction must ensure:

- the original migration exception remains the primary reported error;
- advisory-lock cleanup is not attempted in a PostgreSQL transaction already
  marked failed unless a safe rollback first restores a valid boundary;
- cleanup uses a valid connection or transaction boundary;
- successful and failed runs release the session advisory lock;
- cleanup failure remains secondary and never replaces the migration failure;
- connections and transactions close without leaks;
- competing migration runners remain excluded;
- public errors remain bounded and redact credentials, URLs, hosts, SQL
  parameters, and private topology.

No unrelated runtime refactor is authorized.

## Migration hash exception policy

Migration immutability remains the default and this exception does not
authorize later discretionary edits.

The focused correction must:

1. preserve the pre-correction `0005` blob hash
   `ac5bf41ae5cfefa785006c7eef2a730233e46da9` in this exception ledger;
2. record the post-correction Git blob hash after implementation;
3. record the correction date, approval boundary, baseline commit, correction
   commit, reason, and validation evidence;
4. update migration-integrity validators to accept only the new approved
   `0005` hash;
5. keep every other migration hash unchanged;
6. make any subsequent unapproved `0005` change fail validation;
7. state explicitly in production-readiness handoffs that `0005` received
   this approved compatibility correction.

The old hash must not be erased or represented as the active hash after the
correction.

## Existing-database boundary

The correction is intended for:

- fresh PostgreSQL databases;
- PostgreSQL databases paused before `0005`;
- supported local SQLite databases.

Before implementation, the focused checkpoint must inspect available
evidence for databases already beyond `0005`. If any real deployed database
is found, the checkpoint must stop and require a separate
deployment-specific plan. No production deployment has been claimed, so this
amendment does not invent a production data-migration or rollback procedure.

## Required validation matrix

### Focused `0004` to `0005` transition

Both SQLite and PostgreSQL must prove:

- upgrade `0004 -> 0005`;
- downgrade `0005 -> 0004`;
- re-upgrade `0004 -> 0005`;
- seeded workspace and canonical-object rows survive;
- workspace primary keys remain stable;
- all foreign keys targeting `workspaces` remain present and valid;
- owner backfill and owner foreign key are correct;
- intended columns, indexes, constraints, rows, and values are equivalent;
- no table, constraint, index, or data is silently lost.

### Clean PostgreSQL installation

PostgreSQL 17 with pgvector must prove:

- empty schema upgrade through `20260725_0025`;
- sole head `20260725_0025`;
- pgvector availability;
- intended workspace schema and every referencing foreign key;
- append-only triggers;
- composite user, workspace, canvas, and resource constraints;
- no table, data, constraint, trigger, or index loss.

### Full migration cycle

Both supported validation dialects must prove:

- clean upgrade through `0025`;
- downgrade `0025 -> 0024`;
- re-upgrade `0024 -> 0025`;
- one deterministic schema result and one Alembic head;
- no migration after `0025`;
- no change to later migrations.

### Migration locking and error preservation

Live PostgreSQL tests must prove:

- one runner acquires the advisory lock;
- a competing runner waits or fails safely;
- success releases the lock;
- migration failure releases the lock;
- the original migration error remains primary;
- cleanup errors do not replace it;
- connections and transactions close cleanly;
- public output contains no secret or unredacted database identity.

### SQLite and application regression

The correction checkpoint must run:

- focused migration tests;
- PostgreSQL marker tests;
- Milestone 7.1 tests;
- clean SQLite migration cycle;
- deterministic demo reset, check, and startup smoke;
- full backend, security, and integration suites;
- strict typing, formatting, lint, compilation, imports, and ORM mapping;
- frontend lint, types, tests, production build, and Chromium smoke;
- repository hygiene, secret, local-path, whitespace, diff, migration-hash,
  and protected-reference checks.

## Milestone 7.2 restart gate

Migration `20260726_0026` must remain absent until all of these conditions are
met:

1. this documentation amendment is committed;
2. the migration and runner corrections are implemented in one separate,
   focused checkpoint;
3. the live PostgreSQL clean upgrade, downgrade, and re-upgrade pass;
4. the focused `0004 <-> 0005` matrix passes on PostgreSQL and SQLite;
5. SQLite and deterministic-demo regressions pass;
6. advisory-lock exclusion, release, and original-error preservation pass;
7. the migration exception ledger and active hash validator are updated;
8. every unrelated migration retains its prior hash;
9. the focused correction is committed locally with a clean tree and no
   upstream;
10. no critical or high-severity migration defect remains.

Only after the gate is fully evidenced may Milestone 7.2 restart from the
focused correction commit. The amendment does not authorize migration `0026`,
Indexer implementation, object storage, quarantine, malware scanning,
durable queues, deployment, Milestone 8, the governed Librarian, or later
product-family work.

## Documentation-only confirmation

This amendment changes documentation only. It does not modify migration
`0005`, the guarded runner, tests, dependencies, lockfiles, configuration, CI,
deployment artifacts, or any production feature. Migration `0026` remains
absent and Milestone 7.2 remains unstarted.
