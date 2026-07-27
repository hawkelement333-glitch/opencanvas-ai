# Milestone 7 PostgreSQL Migration 0021 Backfill Current-Role Compatibility Amendment

Date: 2026-07-27

Status: authorized correction implemented and validated locally;
implementation commit pending; Milestone 7.2 not started

## Authoritative documentation baseline

This amendment was prepared from the required clean local baseline:

- repository: SolarPlexus Mobius / `opencanvas-ai`;
- branch:
  `milestone-7-postgresql-historical-migrations-final-corrections-local`;
- commit: `f762e91c879a1da0b77e4c8f6ebddaccbe0d65e6`;
- commit message:
  `Authorize PostgreSQL current-role correction for migration 0021`;
- parent: `6bb7e0433fb0982038fe5bc7e7cba5e30f1f3a59`;
- working tree before this document: clean;
- upstream: none;
- Alembic sole head: `20260725_0025`;
- migrations `0026`, `0027`, and `0028`: absent;
- implementation commit: pending local creation;
- evidence commit: pending local creation;
- Milestone 7.2: not started;
- remote operation: none;
- PostgreSQL: stopped;
- remaining disposable databases: zero.

The documentation-only branch for the committed amendment is:

`milestone-7-postgresql-migration-0021-backfill-current-role-amendment-local`

Its local commit must use:

`Authorize PostgreSQL current-role backfill correction for migration 0021`

The commit containing this document becomes the authoritative documentation
baseline for the next combined historical-migration implementation
checkpoint. Its SHA belongs in the final handoff and migration exception
ledger because a commit cannot contain its own SHA.

This amendment authorizes one additional exceptional correction in historical
migration `20260725_0021`: delimit the one proved bare `current_role`
identifier in the raw owner-backfill `INSERT` target-column list. The combined
checkpoint has now implemented and validated that exact correction without
altering the prior check-constraint or ORM authority, creating a later
revision, or relaxing migration integrity generally.

## Verified isolated database environment and failure

The failure was proved previously in the isolated local environment:

- Ubuntu 24.04.4 under WSL 2;
- PostgreSQL 17.10;
- pgvector 0.8.5;
- PostgreSQL bound only to loopback at `127.0.0.1:55432`;
- no cloud or remote database;
- no production data;
- no production deployment.

The failing live transition was:

`20260725_0020 -> 20260725_0021`

PostgreSQL reached:

`_backfill_owner_memberships()`

and rejected its insertion into:

`workspace_membership_transitions`

The exact affected statement in
`apps/api/alembic/versions/20260725_0021_workspace_memberships_invitations.py`
is:

```sql
INSERT INTO workspace_membership_transitions
(transition_id, membership_id, user_id, workspace_id, sequence,
 previous_state, current_state, previous_role, current_role, reason_code,
 collaboration_policy_version, authority_generation, actor_user_id, trace_id,
 audit_event_id, recorded_at)
VALUES (:transition_id, :membership_id, :owner_id, :workspace_id, 0, NULL,
 'active', NULL, 'owner', 'workspace_owner_backfill', :policy, 1, :owner_id,
 :trace_id, :audit_id, :recorded_at)
```

PostgreSQL reported a syntax error near the bare target-list token:

`current_role`

PostgreSQL recognizes `CURRENT_ROLE` as a special session-role expression.
That grammar does not make the bare token a valid intended column identifier
in this `INSERT` target-column position. The intended existing table column is
the delimited identifier:

`"current_role"`

This failure is distinct from the already documented check-constraint defect.
The prior correction can make the check reference the row column correctly,
but it does not change the raw backfill statement. The live chain therefore
still cannot complete `0021`.

This is not a WSL, PostgreSQL installation, pgvector, migration-runner,
check-parser, UUID-null, trigger-function, ORM-mapping, Indexer, or Milestone
7.2 defect.

PostgreSQL remains stopped during this documentation checkpoint. No database,
credential, or connection string is accessed here.

## Credential boundary

A previous disposable PostgreSQL test credential appeared in transient tool
output. It is not recorded in this document, the repository, a stash, a patch,
or a manifest.

That credential must be rotated outside the repository before the next live
implementation attempt. It must not be reused, printed, copied into a command,
committed, or written to recovery evidence. This amendment does not authorize
accessing or rotating it.

## Preserved implementation and recovery state

The newest and authoritative blocked-work stash is:

`9196c8d9f68c1af6251530f349fdf72638b57b82`

It preserves the most complete separately authorized candidate implementation
and test work. It remains recovery evidence, not active or approved
implementation.

The newest recovery patch is:

`postgresql-historical-corrections-blocked-by-0021-backfill-current-role-keyword-f762e91.patch`

Its verified integrity is:

- size: `235689` bytes;
- SHA-256:
  `56bc94262a36ee59e827d9b2209b5a7ac7a0699b968680b8a28ae9d0bdf2b912`.

The newest recovery manifest is:

`postgresql-historical-corrections-blocked-by-0021-backfill-current-role-keyword-f762e91.manifest.txt`

Its verified integrity is:

- size: `6060` bytes;
- SHA-256:
  `08ec22fcef069f86dc777dd207a33e0abfe333cb7f1c2325fb9281f55c8e4d90`.

The external recovery directory is intentionally not recorded as an absolute
local path.

Earlier immutable stash evidence remains present:

| Recovery checkpoint                   | Stash object                               |
| ------------------------------------- | ------------------------------------------ |
| Prior `0021` check/ORM blocker        | `58ffed44184ea3450a80f5883681da988a196ae7` |
| Trigger-function blocker              | `d50c7020f9b9ce6add83f10d0b443510ccd33ba3` |
| Parser/UUID-backfill blocker          | `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604` |
| Original migration `0005`/runner work | `71b384404468fbfa6326a951ef063e99c9e11652` |

The earlier recorded recovery artifacts remain secondary evidence:

| Evidence                        |           Size | SHA-256                                                            |
| ------------------------------- | -------------: | ------------------------------------------------------------------ |
| Prior `0021` patch              | `213024` bytes | `981b884698d2909ebf2cdeab2173e8f89469a7c1a5c8b25c123bb9e8b5a33f83` |
| Prior `0021` manifest           |   `6894` bytes | `84f327fa1223e95d35bbacc6af3fcd149a9ce9e234c075fbdb84c61ee5edd70b` |
| Trigger-function patch          | `119612` bytes | `2e6726045825fa61d0302d2bc5ac59efca3aa1c1143982aea681998e380b2fca` |
| Trigger-function manifest       |   `5411` bytes | `a39859f68b50cebf70bd1e35982b29a499d9c7e0e47cfb3c17871a7cc1758ab8` |
| Original `0005`/runner patch    |  `25898` bytes | `f165bdd10df4cb95112985396c8ea143c609bf883596ffecd04ae9f9cb9c6f46` |
| Original `0005`/runner manifest |   `1447` bytes | `330c23163a96ba22f16d57710253e4081e93c2b9a9e9bc3f3a5a16ea540c7d11` |

All five stash objects must continue to be located by object SHA rather than
by mutable stash reference number. No stash was applied, popped, changed, or
dropped in this documentation checkpoint. No patch or manifest was modified.

The next implementation checkpoint must use only the newest stash as its
restoration source. Earlier stashes and all patches and manifests remain
immutable recovery evidence.

## Exact affected migration boundary

| Attribute                     | Verified value                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------ |
| File                          | `apps/api/alembic/versions/20260725_0021_workspace_memberships_invitations.py` |
| Revision                      | `20260725_0021`                                                                |
| Direct parent                 | `20260725_0020`                                                                |
| Direct child                  | `20260725_0022`                                                                |
| Function                      | `_backfill_owner_memberships()`                                                |
| Statement                     | Raw `INSERT INTO workspace_membership_transitions`                             |
| Target column                 | `current_role`                                                                 |
| Existing type                 | `String(24)`, not nullable                                                     |
| Inserted application value    | `'owner'`                                                                      |
| Newly unsafe occurrence count | `1`                                                                            |

No other production or migration file receives source-correction authority
from this amendment. Focused tests, migration-integrity evidence,
exception-ledger entries, and narrow documentation remain authorized only as
needed to prove this one correction.

## Complete migration `0021` current-role classification

The baseline migration contains nine lowercase `current_role` tokens, no
authored uppercase `CURRENT_ROLE` token, and no SQL-delimited
`"current_role"` identifier. Python string delimiters around a SQLAlchemy
column name are not SQL identifier delimiters.

| Occurrence | Context                                                              | Classification                       | Authority                   |
| ---------: | -------------------------------------------------------------------- | ------------------------------------ | --------------------------- |
|          1 | `sa.Column("current_role", ...)`                                     | SQLAlchemy column name; safe         | No change                   |
|          2 | `current_role IN (...)` in `ck_workspace_membership_transition_role` | Unsafe bare textual check identifier | Prior `0021` amendment only |
|          3 | `p.current_role` in the SQLite lifecycle trigger                     | Qualified SQL identifier; safe       | No change                   |
|          4 | `NEW.current_role` in the SQLite owner check                         | Qualified trigger-row field; safe    | No change                   |
|          5 | `NEW.current_role` in the SQLite single-owner check                  | Qualified trigger-row field; safe    | No change                   |
|          6 | `t.current_role` in the SQLite single-owner query                    | Qualified relation field; safe       | No change                   |
|          7 | `prior.current_role` in the PostgreSQL lifecycle function            | Qualified record field; safe         | No change                   |
|          8 | `NEW.current_role` in the PostgreSQL owner check                     | Qualified trigger-row field; safe    | No change                   |
|          9 | `current_role` in the owner-backfill `INSERT` target list            | Unsafe bare SQL target identifier    | This amendment              |

There are therefore:

- nine total lowercase tokens in migration `0021`;
- two unsafe bare SQL identifier occurrences in the complete migration;
- one check expression already governed by the prior amendment;
- one newly proved unsafe raw `INSERT` target identifier governed here;
- six safe qualified raw SQL references;
- one safe SQLAlchemy column declaration; and
- exactly one newly authorized correction.

The matching ORM check has its own unsafe bare textual identifier. It remains
exclusively governed by the prior
[migration `0021` current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md).
This amendment adds no ORM production-code authority.

## Complete raw-SQL inspection

Migration `0021` was inspected through its upgrade, downgrade, helper-generated
SQL, SQLite branches, PostgreSQL branches, and `_backfill_owner_memberships()`.

The owner backfill reads:

```sql
SELECT id, owner_id FROM workspaces ORDER BY id
```

For every returned workspace it inserts into:

1. `trace_events`;
2. `collaboration_audit_events`;
3. `workspace_memberships`;
4. `workspace_membership_transitions`;
5. `workspace_authority_versions`.

Only the fourth target-column list contains `current_role`. The other
backfill target lists contain no equivalent occurrence. The migration has no
raw `UPDATE` statement requiring a current-role correction. Its downgrade
deletes trace events only where
`event_type = 'collaboration.membership.backfill'` and
`operation = 'backfill_owner_membership'` before removing the created schema
structures; it does not recreate or reuse the affected target list.

The SQLite and PostgreSQL lifecycle helpers use only qualified
`p.current_role`, `t.current_role`, `prior.current_role`, and
`NEW.current_role` references. Those references resolve fields, not the
session expression, and must remain unchanged.

The repository-wide migration search through sole head `20260725_0025`
identified no second reachable raw `current_role` target-list defect. Later
uses are qualified, including `t.current_role` in migration `0025`.

Migration `0021` also contains no bare identifier occurrence of:

- `current_user`;
- `session_user`;
- `current_schema`;
- `current_catalog`;
- `user`;
- `authorization`.

The standalone word `role` appears in the backfill metadata JSON only as
string data. No additional PostgreSQL keyword or special-expression collision
was proved in a reachable `0021` target or source column list.

If implementation inspection later proves another reachable unsafe occurrence
inside this exact migration and membership-transition boundary, work must
stop and update this amendment before editing. If the affected set extends to
another migration, production file, ORM change beyond the prior amendment, or
another semantic correction, work must stop without implementation.

## Exact owner-backfill semantics

The source is every existing `workspaces` row, ordered by stable workspace
identifier. For each source `(workspace_id, owner_id)` pair, the migration
derives:

- membership ID: UUIDv5 of the workspace ID and `owner-membership`;
- trace ID: UUIDv5 of the workspace ID and
  `owner-membership-backfill-trace`;
- audit ID: UUIDv5 of the workspace ID and
  `owner-membership-backfill-audit`;
- transition ID: UUIDv5 of the membership ID and `transition:0`;
- metadata digest for reason `workspace_owner_backfill`, role `owner`, and
  state `active`.

The one shared `now` value is created once per migration run. Each source row
then inserts the following exact values:

- `trace_events`: event ID UUIDv5 of the trace ID and `event`; trace ID; null
  parent; `occurred_at = now`; event type
  `collaboration.membership.backfill`; `actor_id` equal to the string form of
  the owner UUID; actor type `system`; user ID equal to the owner; workspace
  ID equal to the source workspace; object ID equal to the membership ID;
  object type `workspace_membership`; operation
  `backfill_owner_membership`; status `succeeded`; metadata
  `{"policyVersion":"collaboration-policy-v1"}`; null error;
- `collaboration_audit_events`: deterministic audit ID; source workspace and
  owner actor; subject kind `workspace_membership`; subject ID equal to the
  membership ID; action `membership.bootstrap_owner`; outcome `succeeded`;
  reason `workspace_owner_backfill`; SHA-256 digest of
  `{"reasonCode":"workspace_owner_backfill","role":"owner","state":"active"}`;
  deterministic trace ID; `recorded_at = now`;
- `workspace_memberships`: deterministic membership ID; user and creator
  equal to the owner; source workspace; null accepted invitation; policy
  `collaboration-policy-v1`; deterministic creation trace and audit IDs;
  `created_at = now`;
- `workspace_membership_transitions`: deterministic transition, membership,
  trace, and audit IDs; source owner and workspace; the lifecycle and role
  values listed below; `recorded_at = now`;
- `workspace_authority_versions`: source workspace; authority generation `1`;
  last trace equal to the deterministic trace ID; `updated_at = now`.

The inserted membership transition remains exactly:

- `sequence = 0`;
- `previous_state = NULL`;
- `current_state = 'active'`;
- `previous_role = NULL`;
- `current_role = 'owner'`;
- `reason_code = 'workspace_owner_backfill'`;
- `collaboration_policy_version = collaboration-policy-v1`;
- `authority_generation = 1`;
- actor user equal to the existing workspace owner;
- user and workspace equal to the source owner and workspace;
- trace and audit identifiers equal to the deterministic companion facts.

For `N` valid pre-`0021` workspace rows, the backfill must produce exactly
`N` owner memberships, `N` initial membership transitions, `N` authority
version rows, `N` companion audit events, and `N` companion trace events. For
zero source rows it produces zero of each. It must produce no duplicate owner,
membership, or transition.

The selected correction changes no source row, target column order, bound
parameter, value, ID, timestamp sharing, role, state, reason, policy version,
authority generation, tenant boundary, workspace owner, row count, event, or
evidence fact.

The application role value `'owner'` remains a SQL string literal. It must
never be converted into an identifier, replaced by the database session role,
or derived from `CURRENT_ROLE`.

The completed Milestone 6 semantics remain authoritative:

- membership identity binds one exact user to one exact workspace;
- the role vocabulary remains exactly `owner`, `administrator`, `editor`,
  `approver`, `member`, and `viewer`;
- invitations cannot assign `owner`;
- one workspace has one owner;
- duplicate active memberships and duplicate initial transitions remain
  prohibited;
- tenant, ownership, membership, invitation, authority, audit, Trace, event,
  outbox, and append-only boundaries remain unchanged.

SQLite already accepts the target-list spelling as a column identifier. The
future explicit delimiter is valid SQLite SQL and must preserve equivalent
business behavior.

## Selected deterministic correction

**One resolution is authorized exclusively. No implementation alternative is
left open.**

In the exact raw owner-backfill `INSERT` target-column list, replace:

```sql
previous_state, current_state, previous_role, current_role, reason_code,
```

with:

```sql
previous_state, current_state, previous_role, "current_role", reason_code,
```

The authorized source edit is exactly:

```text
current_role
```

to:

```text
"current_role"
```

at the one proved target-list occurrence.

The future implementation may also add only the focused tests, migration
integrity evidence, exception-ledger entry, and narrow documentation required
to prove and record this authorized correction. The migration source change
itself remains confined to:

`apps/api/alembic/versions/20260725_0021_workspace_memberships_invitations.py`

## Rejected alternatives and risks

### Rely only on the prior check and ORM correction

Rejected. The prior amendment quotes the check constraint and matching ORM
metadata, but it does not alter this raw `INSERT`. PostgreSQL independently
rejects the target list, so the clean chain still cannot complete `0021`.

### Quote role data or use the session role

Rejected and prohibited. `'owner'` is application string data, not an
identifier. Quoting it as an identifier, substituting `CURRENT_ROLE`, or
copying the database login into application data would corrupt role meaning
and violate session-role independence.

### Rename the table, column, or constraint

Rejected and prohibited. Renaming would broaden the correction across
migrations, ORM mappings, services, APIs, tests, and evidence without
improving the one-token repair.

### Rewrite or replace the backfill

Rejected. Converting the statement to a broad SQLAlchemy expression, changing
its source query, restructuring all inserts, or introducing a new backfill
design creates unnecessary behavioral and row-count risk.

### Add a PostgreSQL-only dialect branch

Rejected. ANSI identifier delimiting is valid for PostgreSQL and SQLite. A
new branch would create avoidable cross-dialect drift.

### Quote every current-role reference

Rejected. Qualified `NEW.current_role`, `prior.current_role`,
`p.current_role`, and `t.current_role` references are already unambiguous.
Blanket replacement adds churn and can damage trigger or record syntax. The
complete inventory proves the one new target occurrence.

### Create a corrective child revision

Rejected. A fresh PostgreSQL database cannot finish `0021` and therefore
cannot reach migration `0026` or another child repair.

### Skip, stamp, or parallelize migration history

Rejected and prohibited. Skipping or stamping omits required membership,
transition, invitation, authority, Trace, audit, and lifecycle structures.
A parallel lineage creates competing schema truth and downgrade behavior.

### Weaken constraints or use `CASCADE`

Rejected and prohibited. Neither technique repairs identifier parsing, and
both risk data and integrity loss.

### Activate an intermediate migration hash

Rejected. The final `0021` content must contain both separately approved
migration corrections and must have one final validated active hash. A
check-only or backfill-only active hash would misstate the executable
historical migration.

## Explicitly prohibited changes

The future implementation must not:

- change any migration other than `20260725_0021` under this amendment;
- change another `current_role` occurrence under this amendment;
- rename the table, column, or constraint;
- alter the role registry or invitation-role registry;
- quote role data values as identifiers;
- change the inserted `owner` application role;
- use a database session role as application data or authority;
- change the source workspace or owner rows;
- add, remove, filter, duplicate, or reorder backfilled source rows;
- change deterministic identifiers or inserted row counts;
- change workspace or tenant ownership;
- change membership, invitation, lifecycle, authority, audit, Trace, event,
  outbox, or evidence semantics;
- weaken a check, foreign key, unique constraint, trigger, nullability rule,
  or append-only guard;
- redesign or broadly refactor `_backfill_owner_memberships()`;
- add a dialect branch not already present;
- use `CASCADE`;
- skip or stamp `0021`;
- create a replacement revision or parallel migration lineage;
- modify ORM metadata beyond the separately authorized prior amendment;
- modify dependencies, lockfiles, runtime configuration, CI, or deployment
  implementation;
- activate a provisional or intermediate migration hash;
- create migration `0026`, `0027`, or `0028`;
- start Indexer persistence, Milestone 7.2, deployment, Milestone 8, the
  governed Librarian, or later product-family work;
- contact a Git remote, cloud provider, or production system.

## Relationship to the five prior amendments

This amendment preserves the five prior documentation authorities as separate,
non-overlapping approvals:

1. [Migration `0005` compatibility](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md)
   authorizes only dialect-safe historical migration behavior plus the
   separately bounded guarded-runner correction.
2. [Migrations `0023` and `0024` compatibility](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md)
   authorizes only deterministic check-constraint registry recovery.
3. [Migration `0023` UUID-null compatibility](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md)
   authorizes only the proved PostgreSQL UUID-null typing boundary.
4. [Migrations `0023` and `0024` trigger-function compatibility](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md)
   authorizes exactly four references to the existing deny-all mutation
   function.
5. [Migration `0021` current-role compatibility](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
   authorizes only the quoted check constraint, matching
   `WorkspaceMembershipTransition` ORM metadata, focused parity and
   session-role tests, and their integrity evidence.

The guarded-runner rollback-before-cleanup, advisory-lock exclusion and
release, original-error precedence, secondary cleanup failure, connection and
transaction closure, URL and credential redaction, and focused PostgreSQL and
SQLite tests remain governed by those prior boundaries.

This sixth amendment adds only the one raw owner-backfill target identifier,
its focused tests, and the final combined `0021` integrity record. It does not
broaden any prior migration, runner, ORM, parser, UUID, trigger, membership,
invitation, ownership, tenant, authority, or product authority.

## Migration hash exception policy

Migration immutability remains the default. The protected original migration
`0021` Git blob hash is:

`3baeb7d4deeb5dbf13b230de49ea6a787ce3a0c4`

The original documentation checkpoint changed no hash. The completed combined
implementation activates exactly this final `0021` hash:

`43939e1652e052bbeb3b3de8fd20e052443273d3`

The combined implementation created exactly one final active hash for
migration `0021`. Its final migration content includes:

- the prior approved quoted
  `ck_workspace_membership_transition_role` column identifier; and
- the newly approved quoted owner-backfill target identifier.

The same checkpoint proved matching ORM metadata parity even though the ORM
file is not part of the migration blob.

The exception ledger permanently records:

- the original `0021` hash;
- the one final active `0021` hash;
- the SHA of the prior `0021` check/ORM amendment;
- the SHA of this backfill amendment;
- the final implementation SHA, added by the evidence commit;
- the exact two corrected migration occurrences, classified by their separate
  authorities;
- the matching ORM metadata correction and parity evidence;
- the reason, date, authorized scope, and production-deployment boundary;
- the complete PostgreSQL, SQLite, migration-cycle, and regression evidence.

The validator accepts only the one final validated hash. It rejects:

- the original hash as active after implementation;
- check-only, backfill-only, provisional, or other intermediate hashes;
- a later unapproved edit;
- migration/ORM semantic drift.

Every unrelated migration hash, including `0005`, `0022`, `0023`, `0024`,
and `0025`, must remain unchanged except for each separately authorized final
correction governed by its own amendment. No handoff may claim that corrected
historical migrations remained byte-for-byte untouched.

## Required focused raw-SQL validation

Focused tests must prove:

- the one authorized `current_role` target identifier is exactly
  `"current_role"`;
- the exact `workspace_membership_transitions` target-column order is
  otherwise unchanged;
- the prior check expression is quoted under its separate authority;
- no reachable unsafe bare `current_role` identifier remains in migration
  `0021`;
- all safe qualified current-role references remain unchanged;
- role values remain SQL string data;
- no session-role expression supplies an application role;
- generated PostgreSQL SQL is syntactically valid;
- captured SQLite SQL preserves equivalent behavior;
- the complete nine-token classification remains explainable and guarded by
  focused assertions.

Tests must inspect syntax and semantic identity. A substring assertion that
cannot distinguish a target identifier, check identifier, qualified field,
string value, or session expression is insufficient.

## Required live PostgreSQL owner-backfill validation

Against disposable PostgreSQL 17 with pgvector:

1. start at revision `20260725_0020`;
2. seed the exact valid pre-`0021` workspace and owner state;
3. include multiple workspaces where needed to prove per-workspace counts and
   tenant separation;
4. upgrade to revision `20260725_0021`;
5. prove `_backfill_owner_memberships()` completes;
6. prove exactly one expected membership per source workspace;
7. prove exactly one sequence-zero membership transition per source
   workspace;
8. prove `current_role` contains the application value `owner`;
9. prove the PostgreSQL session role is not inserted and does not affect the
   result;
10. prove exact user, owner, workspace, membership, transition, authority,
    Trace, audit, reason, policy, and generation values;
11. prove exact per-table row counts;
12. prove no duplicate owner, membership, transition, or evidence row;
13. prove tenant and workspace isolation;
14. inject a failure and prove the transaction leaves no partial membership,
    transition, authority, Trace, audit, event, outbox, or other write.

The migration cycle must run under a bounded migration principal with only the
schema DDL rights required by Alembic. Session-role independence must be proved
either by repeating the cycle under two appropriately named disposable
migration principals with the same scoped DDL rights or by comparing
post-migration transition/check DML under two bounded non-DDL principals. No
test may grant superuser, role creation, replication, or RLS-bypass privilege;
schema authority must remain limited to the disposable test schema.

## Required combined migration `0021` validation

The prior and new corrections must be proved together:

- the stored check references the row column, not `CURRENT_ROLE`;
- ORM metadata contains the identical quoted check expression;
- the owner-backfill target identifier is quoted;
- migration-created and metadata-created schemas remain equivalent;
- all six allowed application roles are accepted in valid transition shapes;
- unknown, empty, differently cased, and null current roles are rejected;
- the valid initial owner transition succeeds;
- invitations still cannot assign `owner`;
- the database session role cannot affect validation or inserted data;
- table, column, constraint, type, nullability, registry, and indexes match;
- no migration/ORM schema drift exists;
- invalid data and injected failures leave no partial write.

## Required migration cycles

Live PostgreSQL 17 must prove:

- `0020 -> 0021`;
- `0021 -> 0020`;
- re-upgrade to `0021`;
- an empty schema through sole head `20260725_0025`;
- `0025 -> 0024 -> 0025`;
- deterministic schema, IDs, cardinalities, ownership, scope, role, state,
  policy, and reason values after each supported re-upgrade;
- fresh timestamps are allowed on re-upgrade, while every row created in one
  run must share that run's single `now` value exactly;
- no revision after `0025`;
- one Alembic head.

Downgrade proof must confirm that quoting the upgrade target identifier adds no
new downgrade operation and does not alter the existing data-removal boundary.

No mandatory PostgreSQL test counts as passed when skipped.

## Required SQLite regression

SQLite must prove:

- existing owner-backfill behavior remains semantically equivalent;
- `0020 -> 0021 -> 0020 -> 0021`;
- clean upgrade through `0025`;
- `0025 -> 0024 -> 0025`;
- exact source and inserted row counts;
- the valid initial owner transition and all six roles;
- invalid and null role rejection;
- no migration, schema, data, ORM, membership, invitation, tenant, ownership,
  authority, or evidence regression;
- no PostgreSQL session expression or dialect-only branch enters SQLite SQL.

## Required full combined regression

When the newest stash was restored on the later implementation branch, the
checkpoint was required to validate all separately authorized corrections
together:

- migration `0005` dialect compatibility;
- migration `0021` quoted check identifier;
- migration `0021` quoted backfill target identifier;
- matching `WorkspaceMembershipTransition` ORM metadata;
- migration `0023` and `0024` check parsers;
- migration `0023` UUID-null typing;
- migration `0023` and `0024` trigger-function references;
- all thirteen collaboration append-only update/delete guards;
- preserved migration `0017` domain-event guard;
- guarded-runner rollback before advisory unlock;
- advisory-lock exclusion and release;
- original migration-error precedence;
- cleanup-error secondary precedence;
- transaction and connection closure;
- PostgreSQL URL and credential redaction.

The combined checkpoint was required to run all applicable:

- focused raw SQL, check, ORM parity, role, owner-backfill, migration, parser,
  UUID, trigger, mutation, runner, locking, and redaction tests;
- the complete live PostgreSQL marker suite with zero mandatory skips;
- Milestone 7.1 runtime tests;
- backend, security, and integration suites;
- strict Python typing, formatting, lint, compilation, imports, and mapper
  validation;
- frontend tests, type checking, lint, formatting, production build, and
  browser smoke;
- deterministic demo reset, isolation, check, and startup validation;
- SQLite and PostgreSQL migration-chain validation;
- Alembic sole-head, parent-chain, migration-hash, and ORM/schema-parity
  validation;
- repository hygiene, secret, absolute-local-path, generated-artifact,
  dependency, lockfile, configuration, CI, deployment, whitespace, and diff
  checks;
- Git object integrity and protected-reference verification.

## Historical combined implementation procedure

At this amendment checkpoint, the later combined implementation was required
to:

1. rotate the exposed disposable PostgreSQL test credential outside the
   repository;
2. start a new implementation branch from the exact commit containing this
   amendment;
3. reverify the five stash objects by object SHA;
4. reverify the newest patch and manifest size and SHA-256;
5. reverify every earlier recovery artifact against its recorded integrity
   evidence;
6. apply, not pop, stash
   `9196c8d9f68c1af6251530f349fdf72638b57b82`;
7. preserve every earlier stash, patch, and manifest;
8. review every restored file and hunk against its separate amendment
   authority;
9. implement only the one target-list quote newly authorized here;
10. retain and review the prior authorized migration `0021` check and ORM
    parity changes;
11. add only focused tests, validators, ledger entries, and narrow
    documentation required by the combined corrections;
12. run the focused PostgreSQL and SQLite gates before the full regression;
13. activate final migration hashes only after every mandatory gate passes;
14. create local implementation and final evidence commits;
15. finish with a clean tree, no upstream, and no remote operation.

The newest stash was not to be popped. Any failure during restoration or
implementation was required to preserve it and all secondary recovery
evidence.

## Historical Milestone 7.2 restart gate

At this amendment checkpoint, migration `0026` and Milestone 7.2 remained
prohibited until:

1. this amendment is committed locally;
2. the exposed PostgreSQL test credential is rotated;
3. stash `9196c8d9f68c1af6251530f349fdf72638b57b82` is applied, not
   popped, on a new implementation branch;
4. all earlier recovery evidence remains intact;
5. every restored correction is reviewed against its separate amendment;
6. the prior `0021` check and matching ORM correction are complete;
7. the one backfill target identifier authorized here is corrected;
8. no reachable unsafe bare `current_role` identifier remains in migration
   `0021`;
9. the owner membership backfill succeeds with exact values and counts;
10. the initial owner transition succeeds;
11. all six roles and representative invalid/null roles are proved;
12. session-role independence is proved for checks and inserted data;
13. migration/ORM parity is proved;
14. clean PostgreSQL reaches sole head `20260725_0025`;
15. all required PostgreSQL and SQLite downgrade/re-upgrade cycles pass;
16. exact `0023` and `0024` parser, UUID-null, trigger identity, mutation,
    restart, and rollback behavior passes;
17. guarded-runner locking, rollback ordering, original-error preservation,
    cleanup precedence, closure, and redaction passes;
18. one final migration `0021` hash and all other separately authorized final
    hashes are recorded and activated;
19. every unrelated migration hash remains unchanged;
20. the complete required repository regression passes;
21. local implementation and evidence commits are complete;
22. the working tree is clean with no upstream;
23. no remote operation or deployment occurred;
24. no critical or high-severity historical migration defect remains;
25. migrations `0026`, `0027`, and `0028` remain absent until every gate
    passes.

Only the final combined correction and evidence baseline may authorize a later
restart of checkpoint 7.2.

## Documentation validation requirements

This amendment checkpoint requires:

- repository-standard Markdown formatting;
- valid headings and relative links;
- `git diff --check`;
- staged whitespace validation before commit;
- revision, parent, child, and sole-head consistency;
- exact one-new-occurrence raw SQL assertion;
- complete migration `0021` current-role classification;
- repository-wide keyword-collision and target-list search through `0025`;
- prior-amendment authority and six-amendment count consistency;
- PostgreSQL and SQLite matrix consistency;
- migration-hash and exception-ledger policy consistency;
- credential-rotation and apply-not-pop gate consistency;
- Milestone 7.2, Milestone 8, Indexer, and Librarian boundary scans;
- contradiction and stale-statement scans;
- prohibited-technique scan;
- documentation-only changed-file scope;
- no production code, test, migration, ORM, dependency, lockfile,
  configuration, CI, or deployment implementation diff;
- secret and absolute-local-path scans;
- generated-artifact and repository-hygiene checks;
- Git object integrity, sole-head, current migration-hash, protected-reference,
  all-stash-object, and recovery-integrity checks.

Live PostgreSQL tests and the full application suite must not run during this
documentation-only checkpoint.

## Protected local and remote boundary

All work remains local. This amendment does not authorize:

- fetch, pull, push, or any other remote contact;
- merge, rebase, history rewrite, or commit amendment;
- modifying `main` or moving a protected tag;
- `git reset --hard` or `git clean`;
- applying, popping, dropping, or changing a stash;
- modifying a recovery patch or manifest;
- accessing a credential;
- starting WSL or PostgreSQL;
- creating or retaining a disposable database;
- contacting a cloud provider;
- deploying or provisioning infrastructure.

Protected branches, tags, migration identities, original hashes, stash
objects, recovery artifacts, and the sole Alembic head must remain unchanged
during this documentation checkpoint.

## Original documentation-only checkpoint confirmation

The original amendment checkpoint created documentation only. It did not
modify migration
`0005`, `0021`, `0023`, or `0024`; ORM production code; tests; the guarded
runner; dependencies; lockfiles; runtime configuration; CI; deployment
implementation; or recovery materials.

No stash was applied, popped, changed, or dropped. No migration hash was
activated. No credential was accessed or rotated. Preflight found the enabled
PostgreSQL service active when WSL was inspected; it was stopped without a
database connection before documentation editing, and no PostgreSQL test was
run. No disposable database was created. No remote operation occurred.
Migrations `0026`–`0028` remain absent, and Milestone 7.2 remains unstarted.

At that point, the exact baseline for the next combined implementation
checkpoint was the local commit containing this amendment, with sole head
`20260725_0025`, newest preserved stash
`9196c8d9f68c1af6251530f349fdf72638b57b82`, intact recovery evidence, and
authority to change exactly the one proved raw
`workspace_membership_transitions` target identifier from `current_role` to
`"current_role"`.

## Combined correction validation record

- check/ORM authorization SHA:
  `f762e91c879a1da0b77e4c8f6ebddaccbe0d65e6`;
- owner-backfill authorization SHA:
  `7818be64ee826985952dff1274a07fdf7ebe4ac0`;
- original `0021` hash:
  `3baeb7d4deeb5dbf13b230de49ea6a787ce3a0c4`;
- final active `0021` hash:
  `43939e1652e052bbeb3b3de8fd20e052443273d3`;
- implementation SHA: pending exact local commit.

The owner backfill changes only the target list from `current_role` to
`"current_role"`. Two seeded workspaces prove exact deterministic membership,
transition, Trace, audit, event, and authority identities; exact scope and
cardinalities; the application value `owner`; one transition per membership;
shared timestamps within each run; and fresh timestamps after
`0021→0020→0021`. A failure injected after the first three backfill writes
leaves Alembic at `0020` with no partial table, mutation, lifecycle, authority,
audit, Trace, or row-count change.

The permanent identifier-safety validator rejects bare PostgreSQL-sensitive
identifiers in textual checks and raw insert target lists, accepts quoted,
qualified, data-string, comment, bind, and Python-attribute uses, and scans
both upgrade and downgrade code. Its focused suite passes 18 tests.

This record covers disposable local validation only. It is not evidence of a
production deployment and does not begin Milestone 7.2.
