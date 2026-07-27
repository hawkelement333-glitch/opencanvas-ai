# Milestone 7 PostgreSQL Migration 0021 Current-Role Compatibility Amendment

Date: 2026-07-27

Status: documentation amendment complete locally; correction not implemented;
Milestone 7.2 not started

## Authoritative documentation baseline

This amendment was created from the exact clean local baseline:

- branch:
  `milestone-7-postgresql-trigger-function-compatibility-amendment-local`;
- commit: `6bb7e0433fb0982038fe5bc7e7cba5e30f1f3a59`;
- commit message:
  `Authorize PostgreSQL trigger-function correction for migrations 0023 and 0024`;
- parent: `faa49cad75e7343f0dd7b20aef71ad25c16e318d`;
- original combined-amendment baseline parent:
  `495664668271214cfd84d905d70b93cb47d6869b`;
- working tree: clean;
- upstream: none;
- Alembic sole head: `20260725_0025`;
- migrations `0026`, `0027`, and `0028`: absent;
- Milestone 7.2: not started.

This document is created on
`milestone-7-postgresql-migration-0021-current-role-amendment-local`.
The local commit with message
`Authorize PostgreSQL current-role correction for migration 0021` becomes
the authoritative documentation baseline for the next combined
implementation checkpoint. Its exact SHA belongs in the final handoff because
a commit cannot contain its own SHA.

This amendment authorizes one additional exceptional historical correction:
make the `current_role` check in revision `20260725_0021` and its matching ORM
metadata resolve the table column rather than PostgreSQL's special
`CURRENT_ROLE` expression. It does not implement that correction, modify a
migration or model, apply preserved work, activate a migration hash, create a
later revision, or relax migration integrity generally.

## Verified environment and safety state

The defect was proved during an isolated local implementation attempt using:

- Ubuntu 24.04.4 under WSL 2;
- PostgreSQL 17.10;
- pgvector 0.8.5;
- disposable loopback-only PostgreSQL databases;
- no cloud or remote database;
- no production data or deployment.

At this documentation checkpoint:

- the Ubuntu WSL distribution is stopped;
- PostgreSQL is stopped;
- zero disposable databases remain;
- no database or credential was accessed;
- no live migration or application test was run.

A local PostgreSQL test credential appeared once in transient tool output. It
was not committed or written to a stash, recovery patch, or manifest. It must
be rotated outside the repository before the next live PostgreSQL
implementation attempt. This amendment records no credential value,
connection string, host-private detail, or absolute local recovery path.

## Preserved implementation and recovery state

The most complete blocked implementation work remains outside the working
tree:

- stash object:
  `58ffed44184ea3450a80f5883681da988a196ae7`;
- stash message:
  `postgresql-historical-corrections-blocked-by-0021-current-role-keyword`;
- inventory: 15 tracked files and 5 untracked files;
- recovery patch:
  `postgresql-historical-corrections-blocked-by-0021-current-role-keyword-6bb7e04.patch`;
- recovery patch size: `213024` bytes;
- recovery patch SHA-256:
  `981b884698d2909ebf2cdeab2173e8f89469a7c1a5c8b25c123bb9e8b5a33f83`;
- recovery manifest:
  `postgresql-historical-corrections-blocked-by-0021-current-role-keyword-6bb7e04.manifest.txt`;
- recovery manifest size: `6894` bytes;
- recovery manifest SHA-256:
  `84f327fa1223e95d35bbacc6af3fcd149a9ce9e234c075fbdb84c61ee5edd70b`.

Earlier recovery evidence remains intact:

| Evidence                          | Object or file                                                                                     |           Size | SHA-256                                                            |
| --------------------------------- | -------------------------------------------------------------------------------------------------- | -------------: | ------------------------------------------------------------------ |
| Trigger-function-blocked stash    | `d50c7020f9b9ce6add83f10d0b443510ccd33ba3`                                                         |            N/A | Immutable Git object                                               |
| Parser/backfill-blocked stash     | `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`                                                         |            N/A | Immutable Git object                                               |
| Original `0005`/runner stash      | `71b384404468fbfa6326a951ef063e99c9e11652`                                                         |            N/A | Immutable Git object                                               |
| Trigger-function-blocked patch    | `postgresql-historical-corrections-blocked-by-0023-security-trigger-function-faa49ca.patch`        | `119612` bytes | `2e6726045825fa61d0302d2bc5ac59efca3aa1c1143982aea681998e380b2fca` |
| Trigger-function-blocked manifest | `postgresql-historical-corrections-blocked-by-0023-security-trigger-function-faa49ca.manifest.txt` |   `5411` bytes | `a39859f68b50cebf70bd1e35982b29a499d9c7e0e47cfb3c17871a7cc1758ab8` |
| Original `0005`/runner patch      | `postgresql-0005-runner-provisional-7303386.patch`                                                 |  `25898` bytes | `f165bdd10df4cb95112985396c8ea143c609bf883596ffecd04ae9f9cb9c6f46` |
| Original `0005`/runner manifest   | `postgresql-0005-runner-provisional-7303386.manifest.txt`                                          |   `1447` bytes | `330c23163a96ba22f16d57710253e4081e93c2b9a9e9bc3f3a5a16ea540c7d11` |

All four stash objects were located by object SHA and remain present in the
stash reference inventory. No stash was applied, popped, changed, or dropped.
No recovery patch or manifest was modified.

The newest stash preserves the separately authorized candidate work for
migration `0005`, the guarded runner, migrations `0023` and `0024`, and their
focused tests. These candidate migration hashes remain uncommitted and
inactive:

- `0005`: `79667acf61794c139b2cc27dcf8f2e0598162a5e`;
- `0023`: `e0359af38671b7daa45b6498a4d726c8fde258c0`;
- `0024`: `00303e98659fad0cebabad33f5d5a91635dea4cc`.

They are recovery evidence, not final or active migration hashes.

## Exact affected boundary

| Attribute                   | Verified value                                                                 |
| --------------------------- | ------------------------------------------------------------------------------ |
| Migration file              | `apps/api/alembic/versions/20260725_0021_workspace_memberships_invitations.py` |
| Revision                    | `20260725_0021`                                                                |
| Direct parent               | `20260725_0020`                                                                |
| Parent file                 | `20260725_0020_bounded_agent_studio.py`                                        |
| Direct child                | `20260725_0022`                                                                |
| Child file                  | `20260725_0022_collaboration_roles_permission_authority.py`                    |
| Table                       | `workspace_membership_transitions`                                             |
| Column                      | `current_role`                                                                 |
| Column type and nullability | `String(24)`, not nullable                                                     |
| Constraint                  | `ck_workspace_membership_transition_role`                                      |
| ORM file                    | `apps/api/opencanvas_api/db/models.py`                                         |
| ORM model                   | `WorkspaceMembershipTransition`                                                |
| ORM declaration             | `__table_args__` textual `CheckConstraint`                                     |

The exact closed role registry is:

1. `owner`;
2. `administrator`;
3. `editor`;
4. `approver`;
5. `member`;
6. `viewer`.

The migration and ORM currently contain the same authored textual expression:

```sql
current_role IN (
  'owner',
  'administrator',
  'editor',
  'approver',
  'member',
  'viewer'
)
```

The table column is created as a quoted PostgreSQL identifier by SQLAlchemy,
but the separately authored textual check is passed through without
identifier preparation. PostgreSQL therefore resolves the bare token as the
special expression `CURRENT_ROLE`, not as the row column.

The observed PostgreSQL constraint is equivalent to:

```sql
CHECK (
  (
    CURRENT_ROLE = ANY (
      ARRAY[
        'owner'::name,
        'administrator'::name,
        'editor'::name,
        'approver'::name,
        'member'::name,
        'viewer'::name
      ]
    )
  )
)
```

The `name` casts confirm that PostgreSQL is comparing the database session
role. It is not evaluating the application row's `current_role` value.

## Initial-transition and existing-data semantics

`current_role` is not nullable. The absence of a prior role is represented
only by nullable `previous_role`; the absence of a prior lifecycle state is
represented by nullable `previous_state`.

The deterministic initial workspace-owner transition is:

- `sequence = 0`;
- `previous_state = NULL`;
- `current_state = 'active'`;
- `previous_role = NULL`;
- `current_role = 'owner'`;
- `authority_generation = 1`.

Migration `0021` backfills exactly that transition for each existing workspace.
The runtime owner-bootstrap path uses the same semantics. PostgreSQL currently
rejects the valid transition when the database login name is not in the
application role registry, even though the row value is `owner`.

SQLite resolves the original bare identifier as the table column. Existing
SQLite migration tests therefore accept the owner backfill and reject invalid
role values. The difference is a PostgreSQL parser collision, not a change in
application role meaning.

The future source correction does not require rewriting valid transition
history. It changes how a fresh or pre-`0021` database creates the check and
how ORM metadata describes it. If any real deployed database already beyond
`0021` is discovered, implementation must stop for a deployment-specific,
data-preserving plan rather than treating a historical source edit as an
in-place repair.

## Reachable-chain and keyword-collision inspection

The complete `0021` upgrade and downgrade, its direct parent, and its direct
child were inspected:

- `0020` neither creates nor references workspace membership transitions;
- `0021` creates the affected check once, seeds the initial owner transition,
  and drops the table during downgrade rather than recreating the check;
- `0022` replaces membership lifecycle triggers but does not alter or
  recreate `ck_workspace_membership_transition_role`;
- `0022` downgrade restores the earlier lifecycle trigger, not the check.

Later migration uses of the column are qualified as `NEW.current_role`,
`prior.current_role`, `p.current_role`, or `t.current_role`. Those are
unambiguous field or relation references. Migration `0024` contains no use,
and `0025` uses a qualified `t.current_role` projection.

A full repository and migration-through-`0025` search covered:

- `current_role` and `CURRENT_ROLE`;
- `ck_workspace_membership_transition_role`;
- `current_user`;
- `session_user`;
- `current_schema`;
- `current_catalog`;
- the corresponding PostgreSQL special-expression and reserved-identifier
  set in textual checks.

Exactly two unsafe bare check expressions were found: migration `0021` and
the matching ORM declaration. The `current_user` and `current_schema()` uses
in the database capability probe are intentional session-state queries, not
column references or check constraints. No second reachable migration or ORM
constraint has the same defect.

## Selected deterministic correction

**Explicitly quoted textual SQL is selected for both definitions. No other
implementation strategy is authorized.**

### Migration representation

In the existing `sa.CheckConstraint` for
`ck_workspace_membership_transition_role`, replace only the bare identifier
with the ANSI-delimited identifier:

```sql
"current_role" IN (
  'owner',
  'administrator',
  'editor',
  'approver',
  'member',
  'viewer'
)
```

### ORM representation

In `WorkspaceMembershipTransition.__table_args__`, use the exact same quoted
textual expression and preserve the exact constraint name.

SQLAlchemy 2.0.51 compilation was checked without a live database. It emits
the selected constraint identically for both repository dialects:

```sql
CONSTRAINT ck_workspace_membership_transition_role
CHECK (
  "current_role" IN (
    'owner',
    'administrator',
    'editor',
    'approver',
    'member',
    'viewer'
  )
)
```

The repository declares SQLAlchemy `>=2.0.40,<3` and Alembic `>=1.16,<2`;
the selected form uses stable SQL identifier syntax rather than a
version-sensitive compiler workaround.

This is the smallest deterministic correction because it:

- forces PostgreSQL to resolve the exact table column;
- remains valid SQLite SQL;
- keeps migration DDL and ORM metadata textually and semantically aligned;
- preserves the revision, table, column, constraint, roles, nullability,
  indexes, foreign keys, triggers, data, and downgrade behavior;
- requires no model-column reordering or schema redesign;
- adds no dialect branch or runtime dependency.

## Rejected alternatives and risks

### SQLAlchemy column-expression ORM constraint

Rejected. Directly binding the mapped `current_role` attribute would require
reordering or restructuring the current declarative class because
`__table_args__` currently precedes the mapped column declarations. Using an
unbound `sa.column("current_role")` would still be name-based and would
compile with dialect-dependent quoting. Either choice adds machinery without
improving the two-line repair and makes exact migration/metadata parity harder
to validate.

### Mixed migration text and ORM expression

Rejected. A quoted migration string plus a separate expression-builder form
could be semantically equivalent, but it introduces representational drift
and more complex parity assertions. One identical textual contract is
clearer and deterministic.

### Rename the column

Rejected and prohibited. Renaming `current_role` would broaden the change
across schema history, mappings, services, APIs, tests, and evidence and could
rewrite historical meaning.

### Remove or weaken the check

Rejected and prohibited. Database enforcement of the closed role registry is
required. The correction must not broaden or shrink the allowed set.

### Add a corrective child revision

Rejected for this defect. A fresh PostgreSQL database fails during `0021`
backfill and cannot reach a child correction. Creating `0026`, stamping
`0021`, or maintaining a parallel bootstrap chain would not repair the clean
historical path.

### Add a dialect-specific branch

Rejected. Explicit ANSI identifier quoting works for both supported
validation dialects. A branch would create unnecessary semantic drift.

## Narrow authorized future correction

The next combined implementation checkpoint may modify exactly:

1. the unique migration file for revision `20260725_0021`;
2. the matching `WorkspaceMembershipTransition` ORM constraint declaration;
3. focused PostgreSQL and SQLite regression tests;
4. migration-integrity validators, exception ledgers, and narrow
   documentation required to record and guard the correction.

The correction must:

- preserve revision `20260725_0021` and parent `20260725_0020`;
- preserve the linear child relationship to `20260725_0022`;
- preserve `workspace_membership_transitions`, `current_role`, and
  `ck_workspace_membership_transition_role`;
- preserve `String(24)` and non-null `current_role`;
- preserve nullable `previous_role` and initial-transition semantics;
- preserve the exact six-value role registry;
- preserve valid rows, indexes, foreign keys, triggers, checks, and
  append-only evidence;
- preserve SQLite and supported downgrade/re-upgrade behavior;
- make migration DDL and ORM metadata exactly equivalent;
- make database session identity irrelevant to row validation;
- remain deterministic, focused, and reviewable.

## Explicitly prohibited changes

The future implementation must not:

- rename `current_role` or the constraint;
- remove, bypass, defer, or weaken the check;
- add, remove, reorder semantically, or reinterpret a role;
- make `current_role` nullable;
- replace `previous_role = NULL` with an invented prior role;
- compare application roles to a database login, `CURRENT_ROLE`,
  `CURRENT_USER`, or other session state;
- change role-column types;
- drop, rewrite, or synthesize membership-transition history;
- weaken user, membership, workspace, tenant, ownership, invitation,
  approval, authority, audit, Trace, event, outbox, or append-only contracts;
- use `CASCADE`;
- skip or stamp `0021`;
- create a replacement revision or parallel bootstrap;
- modify another historical migration under this amendment;
- broaden the ORM model change beyond the matching check metadata;
- change dependencies, lockfiles, runtime configuration, CI, or deployment
  implementation;
- activate an intermediate or provisional migration hash;
- create migration `0026`, `0027`, or `0028`;
- start Indexer persistence or Milestone 7.2.

## Relationship to prior amendments

This amendment preserves without broadening:

- [migration `0005` dialect compatibility](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md);
- [migrations `0023` and `0024` check-parser compatibility](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md);
- [migration `0023` UUID-null typing](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md);
- [migration `0023` and `0024` trigger-function references](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md);
- guarded-runner rollback before advisory-lock cleanup;
- advisory-lock exclusion and release;
- original migration-exception precedence;
- URL and credential redaction;
- focused PostgreSQL and SQLite tests required by those boundaries.

Those amendments remain separate authorities. This amendment adds only
revision `0021`, its matching ORM check, focused parity/session-role tests,
and the corresponding migration-integrity evidence. It does not approve the
preserved implementation as complete.

The completed collaboration semantics remain those recorded in the
[Milestone 6.1 handoff](MILESTONE_6_1_WORKSPACE_MEMBERSHIPS_INVITATIONS_HANDOFF.md)
and the
[Milestone 6 migration boundary amendment](MILESTONE_6_MIGRATION_BOUNDARY_AMENDMENT.md).
This compatibility correction changes SQL identifier resolution, not
membership, invitation, role, ownership, or authority meaning.

## Migration hash exception policy

Migration immutability remains the default. The protected original hashes are:

- `0005`: `ac5bf41ae5cfefa785006c7eef2a730233e46da9`;
- `0021`: `3baeb7d4deeb5dbf13b230de49ea6a787ce3a0c4`;
- `0022`: `d4a3bfc1bd32b3df9a886645fba318a51d2ed3a0`;
- `0023`: `01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`;
- `0024`: `fb4e8e264a5a73f2ab543d9cb0fc920ace4fbefb`;
- `0025`: `b5c71452728cf5c473a017679ebb6f2903a5f9f6`.

Only `0021` receives new authority here. The combined implementation
checkpoint must:

1. calculate one final corrected `0021` Git blob hash;
2. preserve the original `0021` hash permanently;
3. record the original and final hashes, this amendment SHA, final
   implementation SHA, reason, date, exact authorized scope,
   production-deployment boundary, and validation evidence;
4. record the matching ORM metadata correction beside the migration
   exception;
5. activate the new hash only after every mandatory validation passes;
6. make the validator accept only that final active hash;
7. keep every unrelated migration hash unchanged;
8. reject later unapproved changes and migration/ORM semantic drift;
9. avoid claiming that migration `0021` remained historically untouched.

Final `0005`, `0023`, and `0024` hashes remain governed by their separate
amendments. Their preserved candidate hashes are not activated here.

## Required focused regression coverage

### PostgreSQL constraint identity

Live PostgreSQL 17 tests must prove:

- exactly one `ck_workspace_membership_transition_role` constraint exists;
- its stored expression references the table column;
- it contains no `CURRENT_ROLE` special expression or session-role `name`
  comparison;
- the database login cannot influence validation;
- the six allowed values are exact;
- no ambiguous or duplicate expression remains.

Catalog inspection must validate semantic identity, not rely only on a
substring that could match a session expression.

### Allowed and invalid values

For each non-null allowed role, PostgreSQL and SQLite must accept a
schema-valid transition. Both must reject:

- an unknown role;
- an empty role;
- a differently cased role;
- a null `current_role`.

ORM-level closed-role validation and database enforcement must remain aligned.
Invitation rules remain unchanged: invitations still cannot assign `owner`.

### Initial owner transition

Both dialects must prove that a valid sequence-zero owner transition succeeds
with:

- `previous_state = NULL`;
- `previous_role = NULL`;
- `current_state = 'active'`;
- `current_role = 'owner'`.

Tests must prove exact row, user, membership, workspace, owner, authority
generation, audit, Trace, event, and outbox preservation. No database-session
role may enter application data or determine the result.

### Session-role independence

Where practical, run the same valid transition under at least two distinct,
authorized, least-privilege disposable PostgreSQL test roles. The row result
must be identical and depend only on table data. Tests must not grant
superuser, role-creation, schema-creation, replication, or RLS-bypass
privilege merely to perform this proof.

### ORM and migration parity

Tests must prove:

- the ORM metadata contains the quoted table-column expression;
- migration-created and metadata-created schemas enforce the same check;
- table, column, constraint name, nullability, and six values match exactly;
- no session expression appears in either representation;
- schema inspection reports no migration/ORM drift.

### Migration cycles

PostgreSQL 17 and SQLite must prove:

- `0020 -> 0021`;
- `0021 -> 0020`;
- re-upgrade to `0021`;
- empty schema through `0025`;
- `0025 -> 0024 -> 0025`;
- the directly affected `0021` cycle under seeded valid workspace data;
- one Alembic head and deterministic schema/data after re-upgrade.

### Transaction and evidence integrity

Failure injection must prove invalid role data and any failed transition leave
no partial mutation, controlled effect, lifecycle transition, membership,
authority generation, invitation consumption, idempotency identity, audit
event, Trace event, domain event, outbox delivery, activity projection, or
lease state.

## Required combined historical validation

After the latest preserved stash is safely restored, validate together:

- migration `0005` dialect-safe correction;
- migration `0021` quoted-column correction;
- `WorkspaceMembershipTransition` ORM parity;
- migration `0023` check parser;
- migration `0023` UUID-null typing;
- migration `0023` trigger references;
- migration `0024` check parser;
- migration `0024` trigger references;
- guarded-runner rollback before advisory unlock;
- advisory-lock exclusion and release;
- original-error precedence and secondary cleanup failure;
- connection and transaction closure;
- URL and credential redaction;
- all applicable SQLite behavior.

Required live and local validation includes:

- focused `0021` constraint, initial-owner, role-registry, session-role, and
  ORM-parity tests;
- focused migration and runner tests;
- the complete live PostgreSQL marker suite with zero mandatory skips;
- the migration `0004/0005`, `0020/0021`, `0022/0023`, `0023/0024`, and
  `0024/0025` cycles required by the five amendments;
- exact `0023`/`0024` registries, UUID-null values, trigger/function
  identities, mutation rejection, restart persistence, and rollback;
- Milestone 7.1, backend, security, and integration suites;
- strict typing, Python formatting and lint, compilation, imports, and mapper
  validation;
- frontend tests, types, lint, formatting, production build, and browser
  smoke;
- deterministic demo reset, isolation, and startup validation;
- SQLite and PostgreSQL migration chains;
- Alembic sole-head, parent-chain, migration-hash, and ORM/schema-parity
  validation;
- repository hygiene, secret, local-path, generated-artifact, dependency,
  lockfile, configuration, CI, deployment, whitespace, diff, Git object, and
  protected-reference checks.

A mandatory PostgreSQL test does not pass when skipped.

## Future combined implementation procedure

The next implementation checkpoint must:

1. rotate the exposed local test credential outside the repository;
2. branch from the exact commit containing this amendment;
3. reverify the four stash objects and every recovery artifact;
4. apply, not pop, stash
   `58ffed44184ea3450a80f5883681da988a196ae7`;
5. preserve all earlier stashes, patches, and manifests;
6. review every restored file against its separate amendment authority;
7. implement only the selected quoted-text `0021` migration and ORM changes
   newly authorized here;
8. add only focused tests, validator/ledger entries, and narrow documentation
   required by the combined corrections;
9. run focused gates before the full combined regression;
10. activate final migration hashes only after every mandatory check passes;
11. create local implementation and final evidence commits;
12. keep the final tree clean, without upstream or remote operation.

## Milestone 7.2 restart gate

Migration `0026` and Milestone 7.2 remain prohibited until:

1. this amendment is committed locally;
2. the exposed local PostgreSQL test credential is rotated outside the
   repository;
3. the newest stash is applied on a new implementation branch without
   removing any recovery evidence;
4. every prior authorized correction is restored and reviewed;
5. migration `0021` and matching ORM metadata use the selected quoted
   identifier;
6. the initial owner transition succeeds;
7. every allowed role and representative invalid/null role is proved;
8. session-role independence is proved;
9. migration/ORM constraint parity is proved;
10. clean PostgreSQL reaches sole head `0025`;
11. all required PostgreSQL and SQLite downgrade/re-upgrade cycles pass;
12. exact `0023`/`0024` parser, UUID-null, trigger identity, mutation,
    restart, and rollback behavior passes;
13. guarded-runner locking, rollback ordering, original-error preservation,
    cleanup precedence, closure, and redaction pass;
14. final migration exception hashes are recorded and activated;
15. every unrelated migration hash remains unchanged;
16. the complete required repository regression passes;
17. implementation and evidence commits are complete locally;
18. the working tree is clean with no upstream;
19. no critical or high-severity migration defect remains;
20. migrations `0026`, `0027`, and `0028` remain absent until every gate
    passes.

Only that final combined correction baseline may authorize a later restart of
checkpoint 7.2.

## Documentation-only confirmation

This checkpoint changes documentation only. It does not modify migration
`0005`, `0021`, `0023`, or `0024`; ORM production code; tests; dependencies;
lockfiles; runtime configuration; CI; deployment implementation; or recovery
materials. No stash was applied, popped, changed, or dropped. No migration
hash was activated. PostgreSQL remained stopped. No credential was accessed.
No remote operation occurred. Migrations `0026`–`0028` remain absent, and
Milestone 7.2 remains unstarted.

The related operating and governance documents are:

- [controlled-agent PostgreSQL testing](CONTROLLED_AGENT_POSTGRES_TESTING.md);
- [controlled-agent data policy](CONTROLLED_AGENT_DATA_POLICY.md);
- [security model](SECURITY_MODEL.md);
- [deployment guide](DEPLOYMENT.md);
- [known limitations](KNOWN_LIMITATIONS.md);
- [Milestone 7 architecture](MILESTONE_7_ARCHITECTURE.md);
- [Milestone 7 architecture handoff](MILESTONE_7_ARCHITECTURE_HANDOFF.md);
- [Milestone 7 implementation plan](MILESTONE_7_IMPLEMENTATION_PLAN.md);
- [Milestone 7 progress](MILESTONE_7_PROGRESS.md);
- [Milestone 7.1 handoff](MILESTONE_7_1_PRODUCTION_RUNTIME_MANAGED_POSTGRESQL_HANDOFF.md).
