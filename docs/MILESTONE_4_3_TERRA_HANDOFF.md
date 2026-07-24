# Milestone 4.3 Terra Handoff

## Rollback-specific capability contract complete locally

- Starting SHA: `8c0fc5b02ca3953065ecacde830c52122ed89734`.
- Capability checkpoint: `2cbc34f4e088a0fdd186db9a0e3b2759d5aaa039`.
- Added closed values: `canvas.note.create.rollback` and `canvas.note.update.rollback`.

The pure mapping permits each value only for its matching inverse note action; it rejects forward
create/update substitution, cross-rollback substitution, and unknown values. No migration is
required because capability strings remain canonical payload data. Focused contract checks: `10 passed`;
Ruff, strict mypy, and diff checks passed. PostgreSQL and network tools were not run.

### Exact next checkpoint

Implement only server-authoritative rollback eligibility review and rollback-approval issuance using
these narrow capabilities. Do not execute a rollback.

## Rollback-authority SQLite validation complete locally

- Starting SHA: `f202e530385bc74781142d330f6a2849aa726502`.
- Validation commit: `a707c88d0d0c64fb9d2b7840745bbf124d616f79`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Database: SQLite only. PostgreSQL runtime was not configured or run.

Focused persistence coverage validates both closed rollback-approval forms and both successful
rollback-result forms; digest, action, target, revision, evidence, grant, scope, uniqueness, and
append-only rejections; plus scoped idempotency and result identity behavior. The focused SQLite
persistence/migration-chain set reported `71 passed`.

The migration cycle upgrades `0013` to `0014`, verifies both tables, named checks, indexes,
foreign-key declarations, and four SQLite mutation-blocking triggers, downgrades to `0013`, confirms
cleanup while rollback evidence remains, then re-upgrades to sole head `0014`.

One defect was corrected: the update rollback-result check now requires non-null, positive
`resulting_revision`; SQLite permits `NULL` through a bare `> 0` expression. No other model or
migration defect was found.

Focused Ruff format/lint, strict mypy, Python compilation, model/migration imports, mapper and
SQLite metadata construction, Alembic head inspection, whitespace/diff, secret-like-material, and
prohibited-scope checks passed. Frontend, unrelated backend/API/service, PostgreSQL, and network
checks were not run.

`main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`; no remote operation occurred.

### Exact next checkpoint

Implement separately authorized server-authoritative rollback review and execution only: revalidate
new approval, effect, evidence, and current state inside one compensating transaction; refuse later
unrelated changes; persist immutable result/audit/Trace evidence. Do not add frontend or Milestone 4.4.

## Rollback-authority migration complete locally

- Starting SHA: `783a55a6f66346d2e12d6d5444c8257f834da93d`.
- Migration commit: `4c8f5c4b30d0e7b87bd5cb57b34fa4d19323f398`
  (`Add rollback authority migration`).
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Migration: `20260724_0014_reversible_write_rollback_authority`, revising `20260724_0013`.

The migration creates `controlled_agent_reversible_write_rollback_approvals` first, followed by
`controlled_agent_reversible_write_rollback_results`. It mirrors the completed ORM contracts:
scope-bound proposal/effect/note/grant relationships for approvals; approval/proposal/effect/note
relationships for results; closed note-create removal and note-update restoration actions; digest,
revision, idempotency, time, and successful-result uniqueness constraints; and all declared lookup
indexes, including Trace correlation on results.

Both tables are append-only. SQLite receives named `BEFORE UPDATE` and `BEFORE DELETE` rejection
triggers. PostgreSQL receives migration-specific rejection functions and combined UPDATE/DELETE
triggers. Downgrade removes result protections/table first, then approval protections/table, leaving
`20260724_0013` and earlier objects untouched.

Static validation at the migration checkpoint:

- Python compilation, module import, down-revision inspection, and Alembic sole-head validation:
  passed (`20260724_0014`).
- Static model-to-migration comparison of both table column lists, named constraints, and indexes:
  passed.
- SQLite and PostgreSQL trigger-definition inspection: passed.
- Focused Ruff format/lint and strict mypy: passed.
- `git diff --check`, whitespace, secret-like-material, and prohibited-scope checks: passed.
- PostgreSQL runtime, Alembic upgrade/downgrade/re-upgrade cycle, persistence tests, frontend tests,
  unrelated backend tests, and network tools: not run.

`main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`. No push, pull, fetch, upstream change, tag operation,
publication, deployment, or GitHub write occurred.

### Exact next checkpoint

Run only rollback-authority SQLite persistence and migration-cycle tests: upgrade from `0013` to
`0014`, inspect both tables/constraints/indexes/triggers, downgrade to `0013`, re-upgrade, then test
valid and rejected approval/result persistence plus append-only behavior. Do not implement rollback
review or execution, routes, frontend work, Milestone 4.4, or Milestone 5.

## Rollback evidence bound to atomic note updates locally

- Starting SHA: `5281d85ab60c4036d1ed8200bd738a8530ae839e`.
- Transaction-integration commit: `8dde7573e3dbdffe78be2ecb19339b47d10c6fa3`
  (`Bind note updates to rollback evidence`).
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Database validation: SQLite only. PostgreSQL was not configured or run.

For an approved `note.update`, the existing nested server-authoritative transaction now captures the
exact mutable state changed by that action—NFC-normalized `title` and `text`—before the compare-and-
set update. It serializes that JSON object with sorted keys, UTF-8, and compact separators, then
stores its SHA-256 digest. It calculates the post-update digest with the same canonical state rule.
The service flushes the immutable effect result and inserts exactly one immutable rollback-evidence
row bound to that effect, proposal, user, workspace, canvas, note, pre-update revision, post-update
revision, before state, and both digests before audit/Trace success records complete.

Creates still produce no rollback-evidence row. Exact duplicate update delivery returns the original
effect and creates neither a second note update, approval consumption, nor evidence row. Older effects
are not backfilled and therefore remain rollback-ineligible without exact authoritative evidence.
Any failure inside the nested transaction rolls back the note update, approval consumption, effect,
rollback evidence, audit success, and Trace success together.

Validation at the integration checkpoint:

- Focused transaction-integration tests: `6 passed`.
- Affected backend group (effects, effect persistence, proposals/approvals, agent API, migrations):
  `56 passed`.
- Focused Ruff format/lint and strict mypy for changed service/tests: passed.
- `git diff --check`, local secret-like-material scan, and prohibited-scope scan: passed.
- Skipped: PostgreSQL, frontend suites, unrelated backend suites, and all network tools.

No rollback execution, rollback review endpoint, frontend work, worker, queue, scheduler, delegation,
provider, or Milestone 4.4/5 behavior was added. `main` remains unchanged and
`competition-demo-v1` remains `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

### Exact next checkpoint

Implement separately authorized server-authoritative rollback review and execution: require a new
approved proposal/key, compare the current note against the evidence after state, create a linked
immutable compensating effect/audit/Trace record, and refuse to overwrite later unrelated changes.

## Rollback-evidence migration cycle validated locally

- Starting SHA: `2c76d113b7477dd5df3df37e2c0aa409785bec59`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Database environment: SQLite only through the repository Alembic/pytest harness. PostgreSQL was
  not configured or run.

Migration `20260724_0013_reversible_write_rollback_evidence` upgraded from `20260724_0012`, created
the rollback-evidence table, named scope/note indexes, composite foreign keys, action/revision checks,
the `ck_agent_rollback_evidence_before_state_object` JSON-object check, and append-only UPDATE/DELETE
triggers. A direct SQLite check proved JSON `null` is rejected and direct UPDATE/DELETE are rejected.
Downgrade to `20260724_0012` removed the evidence table, its triggers, and its parent-effect scope
index while preserving the `20260724_0012` effect table and immutable triggers. Re-upgrade restored
`20260724_0013` as the sole migration head.

The cycle exposed no migration defect. It did expose six stale current-head assertions and one stale
script-directory head assertion in the existing SQLite migration harness; they now expect `0013` when
testing an upgrade to `head`. Explicit `0012` target/downgrade assertions remain unchanged.

Validation:

- SQLite migration-chain suite: `8 passed`.
- Focused rollback-evidence persistence suite: `35 passed`.
- Focused migration-cycle test: `1 passed` before the broader migration-chain run.
- Strict mypy, Ruff format/lint, Python compilation, Alembic import/head validation, and whitespace
  checks: passed.
- Skipped: PostgreSQL execution, unrelated backend/frontend suites, and all network tools.

`main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`. No remote operation, upstream change, or tag operation
occurred.

### Exact next checkpoint

Bind the already-validated rollback evidence into the atomic server-authoritative note-update
transaction. Do not begin rollback execution, frontend work, Milestone 4.4, or Milestone 5.

## Atomic reversible note effect complete locally

- Starting SHA: `177376f76b6c77a89229d5c4ddee69bcf43e3d6b`.
- Atomic-effect implementation commit: `3a959d9d70c45348c7fc4e1553e0afca32fe9647`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.

`ReversibleWriteEffectService` is the sole synchronous, server-authoritative effect path. The
CSRF-protected endpoint accepts only an execution ID and idempotency key. It reconstructs the
persisted proposal, exact preview content, canvas/destination, resource/revision, execution, plan,
grant, and approval server-side; it does not accept client authority, action, content, digest, or
success state.

Within one nested database boundary it checks owned user/workspace/canvas scope, proposal digest and
plan binding, approval decision/expiry, grant expiry/capability/revocation through the authoritative
approval-consumption policy, exact proposal idempotency, and current canvas/revision. Exact duplicate
delivery returns the immutable prior effect. Conflicting keys fail closed. Creation writes one note at
the approved canvas; update uses an exact node-revision compare-and-set. The transaction records
before/after digests, resulting resource/revision, immutable effect result, audit evidence, and
started/succeeded scoped Trace evidence. Any exception rolls back the note, consumption, effect,
audit, and Trace success records.

Focused coverage at `3a959d9`:

- Atomic create, update, exact duplicate, conflicting key, missing execution, stale update, before/
  after evidence, audit/Trace evidence, single consumption, and injected post-mutation rollback:
  `5 passed`.
- Affected proposal, persistence, schema, API, effect-persistence, and migration regressions:
  `59 passed`.
- Strict mypy for the service, endpoint, schemas, and tests; focused Ruff format/lint; `git diff
  --check`; and repository hygiene/secret scan: passed.
- PostgreSQL integration, network tools, frontend checks, and unrelated backend suites: not run.

No rollback feature, frontend work, worker, queue, scheduler, provider, Milestone 4.4, or Milestone
5 work was added. `main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`.

### Exact next checkpoint

Review the atomic effect boundary, then implement separately authorized rollback only: a new approved
proposal/key, after-state compare-and-set, linked immutable compensating effect/audit/Trace evidence,
and refusal to overwrite later unrelated changes. Do not start it automatically.

## Effect-result persistence validated locally

- Starting SHA: `9d2bb55bf3523e46691eb92e4adeda55f8ca2525`.
- Persistence-test checkpoint: `9cb3781c08b09b162579ea6f43e3e0a2cc4db5ed`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none.
- Database environment: SQLite only. PostgreSQL was not configured or run.

The focused tests exposed and corrected two concrete database-integrity gaps before the effect
record could be accepted: proposal and approval IDs are now bound to the same execution, user,
workspace, canvas, and action scope as the effect. The migration also enforces the closed
create/update resource shape: creates cannot carry update-only resource/revision/before-state
fields, while updates require the bound resource, expected revision, matching result resource, and
before-state digest.

The SQLite persistence coverage verifies valid create and update result records; required fields;
proposal, approval, user, workspace, and canvas scope; cross-scope rejection; closed actions and
outcomes; plan-digest presence; scoped idempotency; distinct identities; result uniqueness;
create/update nullable-field combinations; and direct migrated-trigger UPDATE/DELETE rejection.
Migration coverage upgrades `20260724_0011` to `20260724_0012`, confirms the sole head, table,
indexes, constraints, and immutable triggers, downgrades to `20260724_0011` and confirms removal,
then re-upgrades and reruns persistence tests.

Validation at `9cb3781`:

- Focused effect persistence, migration, and reversible-proposal chain: `34 passed` (SQLite).
- Strict mypy for changed tests: passed (2 source files).
- Focused Ruff format and lint: passed.
- Static migration validator: passed upgrade to `20260724_0012`, downgrade to
  `20260724_0011`, and re-upgrade to `20260724_0012`.
- `git diff --check`, repository hygiene/secret scan, and diff-scoped prohibited-scope scan:
  passed.
- Skipped: PostgreSQL integration, unrelated backend/frontend suites, and all network tools.

No remote write, fetch, pull, sync, upstream change, or tag operation occurred. `main` is
unchanged; `competition-demo-v1` remains protected at
`b45b7763b65861f9dfb3be7edf9b5eb271950917`.

### Exact next checkpoint

Implement only the atomic server-authoritative note create/update transaction: reload and verify
the owned proposal/approval/grant/context/plan inside one transaction, consume approval once,
apply the note compare-and-set, persist this immutable effect result with safe audit/Trace evidence,
and roll back every write on denial, conflict, or persistence failure. Do not add a route, rollback
feature, frontend work, worker, queue, scheduler, provider, or Milestone 4.4 work in that checkpoint.

## Phase 1 complete locally: proposal and approval foundation

- Starting Sol handoff: `718ca72e7af6141feb4e6bffc8be9edf74e27995`.
- Documentation correction checkpoint: `90a4e320b373e46ee2bf48ac183a19ba1e6c7fc7`.
- Branch: `milestone-4.3-reversible-writes-local`; no upstream and no remote branch.

## Implemented boundary

`20260724_0011_reversible_write_proposals` persists immutable review-only proposals, scoped to one
user, workspace, canvas, server-owned execution, action, idempotency key, canonical payload digest,
and Trace ID. The service creates only `note.create` or `note.update` proposals, reloads ownership
server-side, binds exact canvas/note revisions, creates existing immutable execution/context/plan/
grant records, and records proposed/awaiting-approval states plus audit evidence. Approval also
fails closed when the grant has already been revoked.

CSRF-protected endpoints create a proposal and explicitly approve its presented proposal digest. An
approval is persisted once and transitions to `ready`; it is not consumed here and no canvas node is
created, updated, deleted, or rolled back. Existing grant expiry, scope, immutable plan, and later
single-use-consumption controls remain authoritative for an effect phase.

## Phase 1 validation

- Proposal/approval, contract, persistence, and API set: `25 passed`.
- New service/route strict mypy: passed.
- New-file Ruff format/lint: passed.
- Migration cycle: upgrade `20260724_0011`, downgrade `20260724_0010`, re-upgrade: passed.
- `git diff --check`: passed before this handoff record.

## Known limits and exact next unit

No workspace effect, approval consumption, rollback, frontend control, worker, queue, scheduler,
delegation, provider, external AI behavior, or Milestone 4.4 code has been added. Phase 2 may add
only the minimal server-authoritative note create/update transaction, consuming the already persisted
approval atomically with compare-and-set revision checks and safe audit/Trace evidence. It must first
add tests for wrong scope, missing/expired/revoked/replayed approval, stale/concurrent revisions,
transaction failure, and exact/conflicting duplicate execution.
