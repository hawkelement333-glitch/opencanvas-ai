# Milestone 4.3 Terra Handoff

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
