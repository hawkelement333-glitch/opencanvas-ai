# Milestone 4.3 Terra Handoff

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
