# Milestone 7 PostgreSQL Migration 0023 UUID Null Compatibility Amendment

Date: 2026-07-26

Status: documentation amendment complete locally; implementation not started;
Milestone 7.2 not started

## Authoritative documentation baseline

This amendment was created from:

- branch:
  `milestone-7-postgresql-migrations-0005-0023-0024-corrections-local`;
- commit: `495664668271214cfd84d905d70b93cb47d6869b`;
- commit message:
  `Authorize PostgreSQL compatibility corrections for migrations 0023 and 0024`;
- parent: `73033862836c45104173ade30cac2bd70cfe181e`;
- Alembic sole head: `20260725_0025`.

The local commit containing this document, with message
`Authorize PostgreSQL UUID null typing in migration 0023`, is the
authoritative baseline for the next combined implementation checkpoint. Its
exact SHA is recorded in the final handoff because a commit cannot contain
its own SHA.

This amendment authorizes one additional, exceptional PostgreSQL
type-compatibility correction in historical migration `20260725_0023`. It
does not implement the correction, apply preserved work, activate a migration
hash, create a later migration, or generally relax migration immutability.

## Preserved implementation and recovery state

The latest combined implementation attempt is preserved outside the working
tree:

- authoritative blocked-work stash object:
  `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`;
- original provisional recovery stash object:
  `71b384404468fbfa6326a951ef063e99c9e11652`;
- original stash message:
  `postgresql-0005-runner-provisional-before-0023-amendment`;
- original external patch SHA-256:
  `f165bdd10df4cb95112985396c8ea143c609bf883596ffecd04ae9f9cb9c6f46`.

Both stash objects remained present, unchanged, unapplied, and undropped
during this documentation checkpoint. The external patch and manifest also
remained intact. This amendment does not approve the preserved implementation
as complete.

After this amendment is committed, the blocked-work stash is the
authoritative recovery source for a new combined implementation branch. The
original stash, patch, and manifest remain secondary recovery evidence.

## Verified environment and failure

The defect was proved using:

- Ubuntu 24.04.4 under WSL 2;
- PostgreSQL 17.10;
- pgvector 0.8.5;
- loopback-only connectivity;
- disposable test databases with credentials stored outside the repository;
- no cloud service, production database, or production data.

The preserved combined attempt produced:

- focused parser, SQLite migration, and runner tests: 46 passed;
- live focused PostgreSQL tests: 3 passed and 3 failed;
- migration `0005` and guarded-runner coverage: passed;
- full regression: not run after the mandatory stop condition.

The three failures all stopped in migration `20260725_0023` before its
corrected constraint behavior could be validated.

## Exact affected migration boundary

| Attribute               | Value                                                                              |
| ----------------------- | ---------------------------------------------------------------------------------- |
| Revision                | `20260725_0023`                                                                    |
| Direct parent           | `20260725_0022`                                                                    |
| Direct child            | `20260725_0024`                                                                    |
| File                    | `apps/api/alembic/versions/20260725_0023_resource_sharing_ownership_revocation.py` |
| Function                | `_backfill_resources()`                                                            |
| Affected dialect branch | PostgreSQL branch only                                                             |
| SQL boundary            | Derived-table `INSERT ... SELECT q.* FROM ({source}) q`                            |

The destination table is `collaboration_resources`. Its affected nullable
UUID columns are:

1. `canvas_id`;
2. `canonical_object_id`;
3. `workflow_definition_id`;
4. `agent_id`;
5. `target_user_id`.

The other destination fields retain their existing typed source values and
are outside this amendment.

## Exact null-placeholder inventory

The PostgreSQL branch defines four source query templates. The affected
placeholders are:

| Source kind        | `canvas_id` | `canonical_object_id` | `workflow_definition_id` | `agent_id`  | `target_user_id` | Static UUID-null placeholders |
| ------------------ | ----------- | --------------------- | ------------------------ | ----------- | ---------------- | ----------------------------: |
| `canvas`           | source UUID | `NULL`                | `NULL`                   | `NULL`      | `NULL`           |                             4 |
| `canonical_object` | `NULL`      | source UUID           | `NULL`                   | `NULL`      | `NULL`           |                             4 |
| `workflow`         | source UUID | `NULL`                | source UUID              | `NULL`      | source UUID      |                             2 |
| `agent`            | source UUID | `NULL`                | `NULL`                   | source UUID | source UUID      |                             2 |

The four templates therefore contain twelve static null placeholders feeding
UUID destinations. Every one must be explicitly UUID typed in the PostgreSQL
branch. The number of inserted SQL nulls at runtime depends on the number of
valid source rows; the static correction boundary is the twelve template
expressions above.

## Root cause

The source query is first enclosed as a derived table and then selected as
`q.*` into `collaboration_resources`. PostgreSQL resolves each standalone
untyped `NULL` output in that derived-table boundary before the outer insert
can apply destination-column context. The resulting source expression is
typed as `text`.

PostgreSQL correctly rejects the first incompatible assignment with:

```text
column "canonical_object_id" is of type uuid but expression is of type text
```

This is an `INSERT ... SELECT` derived-table inference failure. It is not
caused by `UNION`, `UNION ALL`, `VALUES`, `CASE`, `COALESCE`, WSL,
PostgreSQL installation, pgvector, migration `0005`, check-constraint
parsing, guarded-runner cleanup, or Milestone 7.2.

Direct target-context nulls elsewhere in migration `0023`, including trigger
`VALUES` expressions and direct insert-select expressions, are not proved to
have this defect and receive no new authorization.

## Inspection of the reachable chain

Migration `0023` was inspected for UUID, JSON/JSONB, timestamp, boolean,
numeric, array, string-literal, empty-array, `NULL`, `VALUES`, `CASE`,
`COALESCE`, and set-operation inference boundaries.

The equivalent search of migrations `0024` and `0025` found no copy of this
derived-table UUID-null backfill defect:

- `0024` has no equivalent resource backfill or derived-table insert-select;
- `0025` uses bound typed values and target-context `VALUES` nulls rather than
  an independently typed `q.*` source;
- neither migration requires an additional historical correction under this
  amendment.

The proved correction is confined to the PostgreSQL branch of
`_backfill_resources()`. SQLite uses its separate existing branch and does
not require an implementation change.

## Why the prior parser amendment is insufficient

The prior
[migrations 0023 and 0024 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md)
authorizes changes only to check-constraint inspection and allowed-value
recovery. It does not authorize changes to resource backfill SQL or
PostgreSQL expression typing.

The parser correction cannot repair this failure because PostgreSQL stops in
`_backfill_resources()` after the checks are replaced but before migration
`0023` completes. A later revision also cannot repair a clean database that
cannot reach that revision. Skipping or stamping `0023` would omit required
resource, ownership, sharing, authority, trigger, and evidence structures.

The smallest complete exception is therefore explicit UUID typing for the
twelve identified PostgreSQL source placeholders in the existing historical
migration.

## Narrowly authorized future correction

A future combined implementation checkpoint may modify only the PostgreSQL
branch of `_backfill_resources()` in:

`apps/api/alembic/versions/20260725_0023_resource_sharing_ownership_revocation.py`

It may replace each identified untyped UUID-null placeholder with one
deterministic, migration-local PostgreSQL UUID-null expression. Permitted
forms are:

- `NULL::uuid`;
- `CAST(NULL AS uuid)`;
- a repository-consistent SQLAlchemy typed-null expression.

The implementation must select one consistent form based on existing
migration conventions and focused testability.

The correction must:

- preserve revision `20260725_0023`, parent `20260725_0022`, child
  `20260725_0024`, and migration order;
- preserve the intended final schema and UUID destination types;
- preserve all valid existing rows and non-null UUID values;
- preserve intended SQL null semantics;
- type all twelve identified PostgreSQL placeholders;
- preserve upgrade and supported disposable downgrade/re-upgrade behavior;
- preserve SQLite behavior;
- preserve foreign keys, nullability, ownership, tenant scope, authority,
  Trace, audit, and append-only contracts;
- remain deterministic, migration-local, and narrowly reviewable; and
- add only focused PostgreSQL and SQLite regression coverage required for
  this correction.

## Explicitly prohibited changes

The future correction must not:

- convert a UUID destination to text or alter any destination-column type;
- invent a UUID, use a zero UUID, or replace an intended null;
- change a non-null UUID value;
- drop, rewrite, or omit a valid source or destination row;
- weaken foreign keys, nullability, ownership, tenant, authority, audit,
  Trace, evidence, or append-only rules;
- use `CASCADE`;
- skip or stamp migration `0023`;
- create a replacement revision or parallel bootstrap;
- redesign or broadly rewrite `_backfill_resources()`;
- change resource ownership meaning or intended source rows;
- change the SQLite branch without a separately proved requirement;
- modify migration `0024`, `0025`, or another historical migration;
- broaden the check-parser, migration `0005`, guarded-runner, error
  preservation, or URL-redaction authorizations;
- activate a provisional migration hash;
- create migration `0026`, `0027`, or `0028`; or
- begin Indexer, Milestone 7.2, deployment, Milestone 8, Librarian, or later
  work.

## Relationship to prior amendments

This amendment preserves without broadening the existing authority for:

- dialect-safe migration `0005` compatibility;
- migration `0023` and `0024` check-constraint inspection and exact
  allowed-value recovery;
- guarded migration-runner rollback and advisory-lock cleanup;
- original migration-exception preservation;
- PostgreSQL test-URL redaction; and
- the focused PostgreSQL, SQLite, migration, locking, and redaction tests
  needed to prove those changes.

The next combined implementation checkpoint must:

1. branch from the exact commit containing this amendment;
2. verify both stash objects and external recovery materials;
3. apply, not pop, the blocked-work stash
   `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`;
4. review all restored changes against their separate authorization
   boundaries;
5. add only the UUID-null typing and focused tests newly authorized here;
6. keep the original recovery stash and patch as secondary evidence;
7. run the complete combined validation matrix;
8. activate corrected migration hashes only after every mandatory gate
   passes; and
9. commit implementation and final evidence locally without starting
   Milestone 7.2.

## Migration hash exception policy

The protected pre-correction Git blob hash for migration `0023` remains:

`01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`

The prior parser amendment already authorizes one future corrected active hash
for `0023`. The final implementation checkpoint must:

1. calculate one final combined Git blob hash for migration `0023`;
2. preserve the original hash permanently;
3. record that the final content includes both the approved check-constraint
   compatibility correction and this approved UUID-null typing correction;
4. record the exact SHAs of both applicable amendments;
5. record the implementation SHA, reason, date, authorized scope,
   production-deployment boundary, and validation evidence;
6. activate only the final validated combined hash;
7. avoid competing active hashes for the same final migration;
8. keep every unrelated migration hash unchanged; and
9. reject any later unapproved historical edit.

No migration hash changes or becomes active in this documentation checkpoint.

## Required future regression coverage

### PostgreSQL UUID typing

Focused tests must prove:

- every affected placeholder is explicitly UUID typed;
- the derived-table output is no longer `text`;
- intended SQL nulls reach nullable UUID columns without an invented value;
- non-null UUIDs remain exact;
- representative pre-existing source rows and exact row counts survive;
- intended nullable UUID destinations remain null;
- non-null and foreign-key constraints remain enforced; and
- ownership, user, workspace, canvas, and resource scope remain exact.

### PostgreSQL backfill cycle

Against live PostgreSQL 17:

1. begin at `20260725_0022`;
2. seed representative valid canvas, canonical-object, workflow, and agent
   source rows with real UUID values;
3. upgrade to `20260725_0023`;
4. verify exact destination rows, UUID values, SQL nulls, row counts,
   ownership transitions, and tenant scope;
5. verify no text or invented UUID entered a UUID column;
6. downgrade to `20260725_0022` where supported;
7. re-upgrade to `20260725_0023`; and
8. prove deterministic schema and data.

### SQLite behavior

SQLite tests must run the matching `0022 -> 0023 -> 0022 -> 0023` cycle,
preserve the existing branch, and prove equivalent business meaning, exact
rows, UUID strings, intended nulls, ownership scope, and no regression.

### Combined historical correction matrix

After restoring the blocked-work stash, validation must cover:

- migration `0004 -> 0005 -> 0004 -> 0005`;
- migration `0022 -> 0023 -> 0022 -> 0023`;
- migration `0023 -> 0024 -> 0023 -> 0024`;
- empty schema through `20260725_0025`;
- migration `0025 -> 0024 -> 0025`;
- exact `0023` and `0024` closed registries;
- the newly typed `0023` resource backfill;
- seeded-row, primary-key, foreign-key, check, index, trigger, tenant, and
  workspace-scope preservation;
- invalid-value and invalid-null rejection;
- guarded-runner advisory-lock exclusion and release;
- rollback before cleanup SQL;
- original-error precedence over cleanup failure;
- transaction and connection closure; and
- URL and credential redaction.

The clean PostgreSQL chain must reach sole head `20260725_0025` with
PostgreSQL 17, pgvector, expected tables, exact UUID column types, primary and
foreign keys, closed checks, indexes, append-only triggers, tenant/workspace
constraints, and no loss.

The full required regression remains the matrix established by the prior
amendments: focused parser/backfill/migration/locking tests, the complete live
PostgreSQL marker suite, Milestone 7.1, backend, security, integration,
strict typing, Python formatting/lint, frontend tests/types/lint/format/build,
browser smoke, deterministic demo, SQLite and PostgreSQL chains, Alembic
parent/head/hash validation, hygiene, secret/local-path/generated-artifact
scans, dependency/configuration/CI/deployment diff checks, Git whitespace and
object integrity, and protected-reference verification. A mandatory
PostgreSQL skip is not a pass.

## Existing-database and deployment boundary

No production deployment of the affected chain is claimed. The authorized
correction is intended for clean PostgreSQL databases, PostgreSQL databases
paused before `0023`, and supported local SQLite databases.

If a real deployed database is discovered beyond an affected revision, work
must stop for a deployment-specific plan. This amendment does not authorize
production downgrade, data repair, deployment, or provider provisioning.

## Milestone 7.2 restart gate

Migration `20260726_0026` and Milestone 7.2 remain prohibited until:

1. this UUID-null amendment is committed;
2. the blocked-work stash is safely applied on a new implementation branch;
3. all restored changes are reviewed against the prior amendments;
4. all previously authorized corrections and this UUID-null correction are
   complete;
5. focused UUID backfill tests pass on PostgreSQL 17 and SQLite;
6. the clean PostgreSQL chain reaches `0025`;
7. all required PostgreSQL and SQLite downgrade/re-upgrade cycles pass;
8. check-parser, locking, original-error, cleanup-precedence, closure, and
   redaction tests pass;
9. final migration exception records and active hash validators are complete;
10. every unrelated migration hash remains unchanged;
11. the complete repository regression passes;
12. implementation and evidence commits are complete locally;
13. the final working tree is clean with no upstream;
14. no critical or high-severity migration defect remains; and
15. migrations `0026`, `0027`, and `0028` remain absent until every gate
    passes.

Only the final combined correction baseline may authorize a later restart of
checkpoint 7.2.

## Documentation-only confirmation

This amendment changes documentation only. It does not modify migration
`0005`, `0023`, or `0024`; production code; tests; dependencies; lockfiles;
runtime configuration; CI; deployment implementation; or recovery materials.
Neither stash was applied. No migration hash was activated. Migrations
`0026`–`0028` remain absent, and Milestone 7.2 remains unstarted.
