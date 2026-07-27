# Milestone 7 PostgreSQL Migrations 0023 and 0024 Compatibility Amendment

Date: 2026-07-26

Status: combined correction and evidence complete locally; implementation SHA
`a88c6117f6b58137f1014cc8b389f44966c2918f`; Milestone 7.2 not started

Authoritative amendment baseline:

- branch:
  `milestone-7-postgresql-migrations-0023-0024-compatibility-amendment-local`;
- starting commit: `73033862836c45104173ade30cac2bd70cfe181e`;
- starting commit message:
  `Authorize PostgreSQL compatibility correction for migration 0005`;
- starting parent: `62f8f981eb4580d8f174dac44faaf746112891e7`;
- Alembic sole head: `20260725_0025`;
- planned revisions `20260726_0026`, `0027`, and `0028`: absent.

The local commit with message
`Authorize PostgreSQL compatibility corrections for migrations 0023 and 0024`
is the authoritative authorization baseline for the combined implementation
checkpoint. Its exact SHA is recorded in the amendment handoff.

This amendment originally authorized two additional, exceptional
historical-migration compatibility corrections without implementing them. The
combined correction is now implemented and validated locally. It does not
create a later revision or generally relax migration immutability.

Subsequent live PostgreSQL 17 implementation validation proved a separate
derived-table UUID-null type-resolution defect in `0023`'s
`_backfill_resources()`. That defect is outside this amendment's parser-only
authority. The
[migration 0023 UUID-null compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md)
authorizes only explicit UUID typing for the identified PostgreSQL null
placeholders and focused tests. Both amendments remain independently bounded
and apply to the one combined implementation and final `0023` hash.

After the UUID-null correction allowed live PostgreSQL validation to reach
append-only trigger installation, `0023` failed because its `_protect()`
helper references an undefined function. The same name drift exists in
`0024`. The
[trigger-function compatibility amendment](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md)
separately authorizes exactly four reference replacements with the
already-existing deny-all trigger function. It adds no parser, registry,
schema, or Milestone 7.2 authority.

Later combined validation proved a separate PostgreSQL `CURRENT_ROLE`
identifier collision in migration `0021` and its matching ORM constraint. The
[migration 0021 current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
supersedes this document only as the authoritative baseline and recovery
procedure for the next combined implementation checkpoint. It preserves this
amendment's exact `0023`/`0024` parser authority without broadening it.

A still later run proved the separate raw owner-backfill target-list defect in
migration `0021`. The
[migration 0021 owner-backfill current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
is now the authoritative baseline and recovery procedure. It does not broaden
this amendment's exact `0023`/`0024` parser authority.

## Preserved provisional correction boundary

The prior
[migration 0005 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md)
continues to authorize only:

- the dialect-safe correction to revision `20260718_0005`;
- guarded migration-runner rollback and advisory-lock cleanup;
- preservation of the original migration exception;
- PostgreSQL test-URL redaction; and
- the focused PostgreSQL, SQLite, and locking tests needed to prove those
  changes.

That seven-file provisional implementation is preserved outside the working
tree in the named stash
`postgresql-0005-runner-provisional-before-0023-amendment` and separately in
an external recovery patch and manifest. The authoritative stash object is
`71b384404468fbfa6326a951ef063e99c9e11652`. The recovery patch SHA-256 is
`f165bdd10df4cb95112985396c8ea143c609bf883596ffecd04ae9f9cb9c6f46`.
No absolute local recovery path belongs in the repository.

The stash remained unapplied, unchanged, and undropped during the original
documentation checkpoint. It remains recovery evidence, not active
implementation or completion proof. The active branch now contains the
separately reviewed combined `0005`, runner, `0023`, and `0024` corrections;
their final local validation has passed, with the implementation commit
pending.

## Verified environment and affected set

The defect was proved in an isolated local environment:

- Ubuntu 24.04.4 under WSL 2;
- PostgreSQL 17.10;
- pgvector 0.8.5;
- loopback-only connectivity;
- rotated test credentials held outside the repository;
- no cloud service, remote database, production data, or production
  deployment.

A repository-wide search through sole head `20260725_0025` found the fragile
check-value recovery implementation in exactly two reachable migrations:

| Revision        | File                                                     | Parent          | Child           |
| --------------- | -------------------------------------------------------- | --------------- | --------------- |
| `20260725_0023` | `20260725_0023_resource_sharing_ownership_revocation.py` | `20260725_0022` | `20260725_0024` |
| `20260725_0024` | `20260725_0024_comments_collaboration_activity.py`       | `20260725_0023` | `20260725_0025` |

No copied, renamed, or materially equivalent inspected-check parser was found
in another migration through `0025`. Revision `0022` does not inspect its
predecessor constraints: it supplies closed value registries directly.
Revision `0025` does not recover allowed values from inspected check SQL.

## Exact affected constraints and registries

Both migrations recover and replace the same five closed constraints:

| Table                              | Column         | Constraint                             |
| ---------------------------------- | -------------- | -------------------------------------- |
| `domain_events`                    | `event_type`   | `ck_domain_events_type`                |
| `domain_events`                    | `subject_kind` | `ck_domain_events_subject_kind`        |
| `collaboration_request_identities` | `operation`    | `ck_collaboration_request_operation`   |
| `collaboration_request_identities` | `result_kind`  | `ck_collaboration_request_result_kind` |
| `collaboration_audit_events`       | `subject_kind` | `ck_collaboration_audit_subject_kind`  |

The exact `0022` predecessor registries are the immutable values passed by
`20260725_0022_collaboration_roles_permission_authority.py` to
`_replace_checks`:

- event types: `BASE_EVENT_TYPES + NEW_EVENT_TYPES` — 74 values;
- domain-event subject kinds:
  `(*BASE_SUBJECT_KINDS, NEW_SUBJECT_KIND)` — 21 values;
- request operations:
  `BASE_REQUEST_OPERATIONS + NEW_REQUEST_OPERATIONS` — 12 values;
- request result kinds: `workspace_invitation`, `workspace_membership`, and
  `approval_authority_assignment`;
- audit subject kinds: `workspace_membership`, `workspace_invitation`, and
  `approval_authority_assignment`.

Revision `0023` must add, and its downgrade must remove, exactly:

- event types: `resource.share.created`, `resource.share.changed`,
  `resource.share.revoked`, `resource.share.expired`,
  `resource.visibility.changed`, `resource.ownership_changed`,
  `ownership_transfer.requested`, `ownership_transfer.accepted`,
  `ownership_transfer.rejected`, `ownership_transfer.canceled`, and
  `revocation.bulk_completed`;
- domain-event and audit subject kinds: `resource_share_request`,
  `collaboration_resource`, `ownership_transfer`, and `authority_fence`;
- request operations: `share.create`, `share.revoke`, `share.bulk_revoke`,
  `resource.visibility.change`, `ownership_transfer.request`,
  `ownership_transfer.accept`, `ownership_transfer.reject`, and
  `ownership_transfer.cancel`;
- request result kinds: `resource_share`, `collaboration_resource`,
  `ownership_transfer`, and `authority_fence`.

Its exact resulting registry sizes are 85 event types, 25 domain-event subject
kinds, 20 request operations, 7 request result kinds, and 7 audit subject
kinds.

Revision `0024` must add, and its downgrade must remove, exactly:

- event types: `comment.created`, `comment.reply.created`, `comment.revised`,
  `comment.tombstoned`, `comment.thread.resolved`, and
  `comment.thread.reopened`;
- domain-event subject kinds: `comment_thread` and `comment`;
- request operations: `comment.create`, `comment.reply`, `comment.revise`,
  `comment.tombstone`, `comment.thread.resolve`, and
  `comment.thread.reopen`;
- request result kinds: `comment_thread`, `comment`, `comment_revision`,
  `comment_transition`, and `comment_thread_transition`;
- audit subject kinds: `comment_thread`, `comment`, `comment_revision`, and
  `comment_transition`.

Its exact resulting registry sizes are 91 event types, 27 domain-event subject
kinds, 26 request operations, 12 request result kinds, and 11 audit subject
kinds.

The immutable predecessor registries and the exact deltas above, rather than
parser output order or counts alone, define the allowed-value contract. Final
validation must compare the complete sets.

## Verified dialect representations and parser defect

SQLite inspection at revisions `0022` and `0023` returns the authored shape:

```sql
event_type IN ('value_a', 'value_b', 'value_c')
```

A live PostgreSQL 17 and SQLAlchemy inspection probe proved that PostgreSQL
canonicalizes the same constraint as:

```sql
event_type::text = ANY (ARRAY['value_a'::character varying, 'value_b'::character varying, 'value_c'::character varying]::text[])
```

Both affected helpers take the substring between the first `(` and last `)`
and call `split(",")`. That operation does not parse SQL structure. On
PostgreSQL it:

- splits array elements at syntax-level commas;
- retains `ARRAY`, casts, parentheses, and quote fragments as if they were
  domain values;
- cannot distinguish commas inside SQL syntax or quoted literals;
- cannot safely handle escaped quotes, cast spelling, harmless whitespace,
  nested parentheses, or other valid deparser differences; and
- feeds malformed fragments to `_in`, which quotes them again and produces
  invalid replacement check SQL.

The observed clean-chain failure occurred while `0023` attempted to recreate
`ck_domain_events_type`, with PostgreSQL reporting a syntax error near
`graph`. This is a production-engine compatibility defect, not a WSL,
installation, pgvector, offline-DDL, migration `0005`, runner, or Milestone
7.2 defect.

## Why both corrections are required

Correcting only `0023` is knowingly incomplete:

1. corrected `0023` creates the intended closed constraint;
2. PostgreSQL canonicalizes it to `ANY (ARRAY[...])`;
3. direct child `0024` inspects that canonical expression;
4. `0024` applies the materially identical comma parser; and
5. the chain fails before it can reach `0025`.

A later revision cannot repair a fresh database that cannot pass `0023` or
`0024`. Stamping either revision would omit required tables, constraints,
triggers, backfills, and evidence contracts. A parallel bootstrap would create
divergent histories, ambiguous release artifacts, and incompatible downgrade
semantics. The smallest complete exception is therefore one transparent,
hash-ledgered compatibility correction in each of the two affected files.

## Narrowly authorized corrections

The combined implementation is limited to exactly:

- `apps/api/alembic/versions/20260725_0023_resource_sharing_ownership_revocation.py`;
- `apps/api/alembic/versions/20260725_0024_comments_collaboration_activity.py`.

Within each file it may change only the check-constraint inspection and
allowed-value recovery logic required for deterministic behavior on the
approved SQLite and PostgreSQL dialects.

The corrections must:

- preserve both revision identifiers, parents, children, and migration order;
- preserve intended upgrade and downgrade behavior;
- preserve every valid row and the exact closed registries above;
- preserve or strengthen check enforcement;
- produce equivalent semantic results on SQLite and PostgreSQL 17;
- recognize the actual PostgreSQL `ANY (ARRAY[...])` representation,
  legitimate casts, SQL quoting and escaped quotes, harmless whitespace, and
  parenthesis differences;
- fail closed on missing, unknown, malformed, or ambiguous expressions;
- avoid evaluating or executing introspected SQL;
- avoid interpreting syntax, casts, or commas as domain values;
- avoid widening, reordering semantically, or silently emptying a registry;
  and
- remain deterministic, self-contained, and locally reviewable.

A narrowly shared parser is permitted only if migration architecture can
freeze it immutably for both historical revisions. Importing a mutable runtime
helper is not permitted. Otherwise each migration remains self-contained.

## Explicitly prohibited changes

The combined correction must not:

- use `CASCADE`;
- skip or stamp either migration;
- create replacement revisions or a parallel bootstrap;
- redesign any affected table or domain;
- add, remove, or accept an unintended value;
- weaken, remove, bypass, or broadly disable checks or triggers;
- drop application data;
- special-case only the literal `graph`;
- continue naive comma splitting;
- evaluate or execute introspected SQL;
- silently accept unsupported syntax;
- convert ambiguity into an empty or broader set;
- modify any other historical migration;
- broaden the guarded-runner correction;
- alter tenant, authority, audit, Trace, evidence, or append-only contracts;
- create migration `0026`, `0027`, or `0028`; or
- include Indexer or other Milestone 7.2 implementation.

## Migration hash exception policy

Migration immutability remains the default. This amendment permanently
preserves these pre-correction Git blob hashes:

- `0005`: `ac5bf41ae5cfefa785006c7eef2a730233e46da9`;
- `0023`: `01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`;
- `0024`: `fb4e8e264a5a73f2ab543d9cb0fc920ace4fbefb`.

The provisional uncommitted `0005` hash
`79667acf61794c139b2cc27dcf8f2e0598162a5e` remains provisional evidence. Its
bytes are also the selected final `0005` content, but the provisional
designation remains part of the permanent history.

The preserved pre-trigger combined attempt produced these intermediate,
non-active hashes:

- `0023`: `b1c3b66307805a43386959f511a91dd9fc66d0f8`;
- `0024`: `1932ac1b9da9e7cc4f6b01badf55fe2c2c308301`.

The combined implementation activates only these final hashes:

- `0005`: `79667acf61794c139b2cc27dcf8f2e0598162a5e`;
- `0023`: `cb7138d9de806e1546c3853944b1816a98da1d67`;
- `0024`: `cc29d1280af1a4110ec42b7f0fa782f710dcfeb5`.

The final `0023` content includes the approved parser, UUID-null, and
trigger-reference corrections. The final `0024` content includes the approved
parser and trigger-reference corrections. Original and intermediate hashes
remain evidence but are not active. Validators select only the final hashes;
every unrelated migration hash must remain unchanged, and any later
unapproved edit must fail validation. Final test evidence is recorded below;
the local correction commit identity is added by the evidence commit.

## Required combined validation

Before implementation, re-scan through `0025` and stop if another equivalent
reachable parser defect is proved.

### Migration 0005 and runner

On PostgreSQL 17 and SQLite, prove `0004 -> 0005 -> 0004 -> 0005`, seeded
workspace and dependent canonical-object preservation, stable primary and
foreign keys, and equivalent intended schema. Prove one migration runner
excludes competitors, releases its advisory lock after success and failure,
rolls back before failure cleanup SQL, preserves the original exception,
keeps cleanup failures secondary, closes transactions and connections, and
redacts URLs and credentials.

### Migration 0023

Prove `0022 -> 0023 -> 0022 -> 0023` on PostgreSQL 17 and SQLite. Seed valid
rows for every exact intended value, preserve them, compare complete resulting
sets, reject invalid values, inspect actual constraint forms, handle casts,
quotes, escaped literals, whitespace, arrays, and parentheses, and fail closed
on unsupported or ambiguous input without generating invalid SQL.

### Migration 0024

Begin from corrected `0023` output and prove
`0023 -> 0024 -> 0023 -> 0024` on PostgreSQL 17 and SQLite. Seed and preserve
every exact intended value, compare complete sets, reject invalid values,
prove corrected `0024` consumes PostgreSQL-canonicalized corrected `0023`
output, and fail closed on unsupported forms.

### Cross-migration and complete-chain proof

Prove corrected `0023` output is consumed by corrected `0024`, corrected
`0024` downgrade output is consumable by corrected `0023`, casts and array
syntax never become values, syntax-level commas do not become separators,
quoted values remain intact, no introspected SQL executes, and all valid rows
survive.

Against clean disposable PostgreSQL 17 with pgvector, migrate from empty
schema through `0025`; verify the recorded version, sole head, tables, primary
and foreign keys, exact checks, indexes, append-only triggers, tenant and
workspace constraints, and no loss. Then prove `0025 -> 0024 -> 0025`, the
supported `0022` through `0024` focused cycles, deterministic schema and data,
one head, and no revision after `0025`.

Run corresponding SQLite clean, `0004/0005`, `0022/0023`, `0023/0024`, and
`0025/0024` cycles; deterministic demo reset/check/smoke; existing SQLite
migration and application suites; all focused/live PostgreSQL, Milestone 7.1,
backend, security, integration, typing, Python formatting/lint, frontend
tests/types/lint/format/build, browser smoke, migration chain/hash, hygiene,
secret, local-path, generated-artifact, whitespace, Git-object, and protected
reference validation. A required PostgreSQL skip is not a pass.

## Existing-database and deployment boundary

No production deployment of this chain has been claimed. The corrections are
intended for fresh PostgreSQL databases, PostgreSQL databases paused before
an affected revision, and supported local SQLite databases. If a real
deployed database is discovered beyond an affected revision, stop and require
a deployment-specific plan. This amendment does not invent a production
downgrade or data-repair procedure.

## Milestone 7.2 restart gate

Migration `20260726_0026` and Milestone 7.2 remain prohibited until:

1. this combined amendment is committed;
2. the preserved provisional work is safely reapplied on a new implementation
   branch;
3. the separately authorized `0005`, runner, `0023`, and `0024` corrections
   are complete;
4. all three migration exception records and active hash validation are
   complete;
5. the full PostgreSQL clean and focused migration cycles pass;
6. the full SQLite migration regressions pass;
7. cross-migration `0023/0024` compatibility passes;
8. lock release, rollback ordering, original-error preservation, cleanup
   precedence, connection closure, and redaction pass;
9. all unrelated migration hashes remain unchanged;
10. the complete repository regression passes;
11. the combined correction is locally committed with a clean tree and no
    upstream;
12. no critical or high-severity migration defect remains; and
13. migrations `0026`, `0027`, and `0028` remain absent until this gate passes.

The successor UUID-null amendment added explicit `0023` resource-backfill
typing and focused regression conditions to this gate. The later
trigger-function and two `0021` current-role amendments completed the six
amendments' shared gate, which has now passed locally.

Only the final clean evidence commit may become the authoritative baseline for
restarting Milestone 7.2; its SHA is reported in the final handoff because a
commit cannot record its own identity. This amendment does not authorize
Indexer persistence, object storage or quarantine, malware scanning, durable
queue expansion, deployment, Milestone 8, the governed Librarian, or later
product-family work.

## Amendment history and current state

The original amendment checkpoint changed documentation only. The separately
authorized combined correction is now implemented and validated locally, with
the final hashes above active. Preserved stashes, patches, manifests, original
hashes, and intermediate hashes remain recovery or historical evidence rather
than active migration content. Migrations `0026`–`0028` remain absent, and
Milestone 7.2 remains unstarted.

## Combined correction validation record

- parser authorization SHA:
  `495664668271214cfd84d905d70b93cb47d6869b`;
- trigger authorization SHA:
  `6bb7e0433fb0982038fe5bc7e7cba5e30f1f3a59`;
- original `0023` hash:
  `01c9b28d7b2875a7cfe7041fc846f79d7c672aa5`;
- final active `0023` hash:
  `cb7138d9de806e1546c3853944b1816a98da1d67`;
- original `0024` hash:
  `fb4e8e264a5a73f2ab543d9cb0fc920ace4fbefb`;
- final active `0024` hash:
  `cc29d1280af1a4110ec42b7f0fa782f710dcfeb5`;
- implementation SHA: `a88c6117f6b58137f1014cc8b389f44966c2918f`;
- evidence commit: this documentation-only commit; exact SHA reported in the
  final handoff.

The final `0023` bytes include the closed parser, twelve typed UUID-null
placeholders, and two trigger-function corrections. The final `0024` bytes
include the closed parser and two trigger-function corrections. Live cycles
proved exact predecessor/successor registries, `0022→0023→0022→0023`,
`0023→0024→0023→0024`, all thirteen protected triggers, valid inserts,
rejected updates and deletes, preserved rows, and the unchanged normal
domain-events trigger.

Original and intermediate hashes remain non-active evidence. No production
deployment or later milestone is authorized by this record.
