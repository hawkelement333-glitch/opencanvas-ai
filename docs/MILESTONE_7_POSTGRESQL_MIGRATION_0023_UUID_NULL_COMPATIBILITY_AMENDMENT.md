# Milestone 7 PostgreSQL Migration 0023 UUID Null Compatibility Amendment

Date: 2026-07-26

Status: combined correction and evidence complete locally; implementation SHA
`a88c6117f6b58137f1014cc8b389f44966c2918f`; Milestone 7.2 not started

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
historical UUID-null authorization baseline. A later
[trigger-function compatibility amendment](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md)
supersedes it as the authoritative baseline for the next combined
implementation checkpoint after live validation proved a separate undefined
trigger-function reference. That amendment does not broaden the UUID-null
authority recorded here.

A still later combined run proved a separate PostgreSQL `CURRENT_ROLE`
identifier collision in migration `0021` and its matching ORM constraint. The
[migration 0021 current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
then supplied the authoritative baseline, preserved-stash identity, and
restart procedure for that combined checkpoint. It does not broaden the
UUID-null authority recorded here.

A still later run proved the separate raw owner-backfill target-list defect in
migration `0021`. The
[migration 0021 owner-backfill current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
now supplies the authoritative baseline, preserved-stash identity, and restart
procedure. It does not broaden the UUID-null authority recorded here.

This amendment authorizes one additional, exceptional PostgreSQL
type-compatibility correction in historical migration `20260725_0023`. It
does not implement the correction, apply preserved work, activate a migration
hash, create a later migration, or generally relax migration immutability.

## Preserved implementation and recovery state

The parser/UUID implementation attempt originally governed by this amendment
is preserved outside the working tree:

- blocked-work stash object:
  `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`;
- original provisional recovery stash object:
  `71b384404468fbfa6326a951ef063e99c9e11652`;
- original stash message:
  `postgresql-0005-runner-provisional-before-0023-amendment`;
- original external patch SHA-256:
  `f165bdd10df4cb95112985396c8ea143c609bf883596ffecd04ae9f9cb9c6f46`.

Both stash objects remained present, unchanged, unapplied, and undropped
during the original documentation checkpoint. A later combined attempt added
the authorized UUID typing and tests, then stopped at the trigger-function
defect. The most complete preserved recovery source is stash
`d50c7020f9b9ce6add83f10d0b443510ccd33ba3`, with patch SHA-256
`2e6726045825fa61d0302d2bc5ac59efca3aa1c1143982aea681998e380b2fca`
and manifest SHA-256
`a39859f68b50cebf70bd1e35982b29a499d9c7e0e47cfb3c17871a7cc1758ab8`.
The two earlier stashes, original patch, and original manifest remain
secondary evidence. The active branch now contains the separately reviewed
combined implementation. The preserved materials remain recovery evidence,
not active content or completion proof.

Historical note: the statement above records the recovery state at this
amendment's own checkpoint. The migration `0021` check/ORM amendment records
the later stash `58ffed44184ea3450a80f5883681da988a196ae7`. Its owner-backfill
successor records the current stash and exclusively governs future
application.

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

## Narrowly authorized correction

The combined implementation is limited to the PostgreSQL
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

The authorized correction must not:

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

At this amendment's completion, the next combined implementation checkpoint
had to:

1. branch from the exact commit containing this amendment;
2. verify both stash objects and external recovery materials;
3. apply, not pop, the blocked-work stash
   `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`;
4. review all restored changes against their separate authorization
   boundaries;
5. add only the UUID-null typing and focused tests newly authorized here;
6. keep the original recovery stash and patch as secondary evidence;
7. run the complete combined validation matrix;
8. activate only the final corrected migration hashes, never an intermediate
   hash, for the mandatory validation matrix; and
9. commit implementation and final evidence locally without starting
   Milestone 7.2.

That recovery-selection procedure is historical. The successor `0021`
current-role amendment replaces the branch and stash selection with its newer
verified baseline and stash while retaining every UUID-null condition above.

## Migration hash exception policy

The protected pre-correction Git blob hash for migration `0023` remains:

`01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`

The prior parser amendment authorizes one corrected active hash for `0023`.
The exception ledger preserves:

- original `0023` hash:
  `01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`;
- intermediate pre-trigger `0023` hash:
  `b1c3b66307805a43386959f511a91dd9fc66d0f8`;
- final active `0023` hash:
  `cb7138d9de806e1546c3853944b1816a98da1d67`.

The final content includes the approved check-constraint parser, UUID-null,
and trigger-reference corrections. The original and intermediate hashes
remain permanent evidence and are not active. Validators select only the final
active hash, keep every unrelated migration hash unchanged, and reject later
unapproved historical edits. The combined ledger also activates `0005`
`79667acf61794c139b2cc27dcf8f2e0598162a5e` and `0024`
`cc29d1280af1a4110ec42b7f0fa782f710dcfeb5`. Final validation evidence is
recorded below; the local correction commit identity is added by the evidence
commit.

## Required final regression coverage

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

The latest `0021` owner-backfill current-role amendment adds its
credential-rotation and raw-target conditions to the earlier quoted-column,
ORM-parity, and session-role-independence conditions and governs the current
recovery procedure.

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

## Amendment history and current state

The original amendment checkpoint changed documentation only. The separately
authorized combined correction is now implemented and validated locally, and
its final hashes are active. Preserved recovery materials and intermediate
hashes remain evidence rather than active migration content. Migrations
`0026`–`0028` remain absent, and Milestone 7.2 remains unstarted.

## Combined correction validation record

- UUID-null authorization SHA:
  `faa49cad75e7343f0dd7b20aef71ad25c16e318d`;
- parser authorization SHA:
  `495664668271214cfd84d905d70b93cb47d6869b`;
- trigger authorization SHA:
  `6bb7e0433fb0982038fe5bc7e7cba5e30f1f3a59`;
- original `0023` hash:
  `01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`;
- final active `0023` hash:
  `cb7138d9de806e1546c3853944b1816a98da1d67`;
- implementation SHA: `a88c6117f6b58137f1014cc8b389f44966c2918f`;
- evidence commit: this documentation-only commit; exact SHA reported in the
  final handoff.

Static and live PostgreSQL evidence proves exactly twelve
`NULL::uuid` placeholders across the approved `4/4/2/2` source-query
distribution. Real UUIDs remain exact, intended nulls remain null, SQLite
semantics are unchanged, foreign keys still reject unknown UUIDs, and the
`0022→0023→0022→0023` cycle preserves the resource and ownership rows.

This record activates no broader UUID or schema rewrite and represents no
production deployment.
