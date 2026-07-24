# Milestone 4.3 Sol Handoff

## MILESTONE 4.3 SOL ARCHITECTURE COMPLETE LOCALLY — READY FOR TERRA

## Baseline and local safety

- Authorized starting SHA: `21aee1f86b47424ee774f3245c0d0d3599215846`.
- Local branch: `milestone-4.3-reversible-writes-local`; upstream: none.
- Architecture checkpoint: `e7f18d5299b365a98caeb46413f6efed007130a5`.
- Remote freeze: no push, remote branch, tag, pull request, release, upload, or GitHub write occurred.
- Protected tag object: `acbde89b6e2cc3e41c372887794726d393836716`.
- Protected peeled demo commit: `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- `main` is untouched.

## Completed Sol boundary

Only a future minimal note creation or note update on one owned canvas is designed. Closed actions
are `note.create` and `note.update`; matching closed capabilities are `canvas.note.create` and
`canvas.note.update`. Every future effect binds server-owned execution, user, workspace, canvas,
destination, optional exact note/revision, bounded preview, canonical proposal digest, expiring
approval, CSRF-protected session, and idempotency key.

The only code is frozen strict pure contracts: `ReversibleWriteProposal`,
`ReversibleWriteAction`, and `NotePreview`. There is no route, persistence, mutation, UI control,
provider, worker, queue, scheduler, or active effect. Tests cover digest binding and invalid action,
destination, create/update, and revision contracts. Existing policy remains authoritative for grants,
expiry, revocation, replay, scope, and plan/context hashes.

## Transaction, rollback, audit, and Trace

Future Terra work must reread authority and revisions inside one transaction, re-evaluate policy,
atomically consume approval, apply compare-and-set, and persist before/after evidence plus safe audit
and Trace events or roll back. Exact duplicates return the prior terminal result; conflicting
idempotency reuse fails closed. Rollback is unimplemented: it needs new approval, a new key,
after-state compare-and-set, and must refuse to overwrite later unrelated work.

Audit/Trace must retain safe identifiers, plan digest, scope, policy/approval/idempotency outcome,
before/after revisions and content digests, reason, actor, timestamps, Trace ID, and rollback link.
It must omit secret/session/CSRF/auth data, hidden prompts, paths, and unnecessary note bodies.

## Migration, API, UI, and demo plan

No migration is added. Terra may add one only if current persistence cannot atomically retain the
proposal, consumption, idempotency, and evidence. It needs workspace-scoped constraints/indexes and
migration tests. The first API is proposal/approval only: authenticated, CSRF-protected, and
server-reconstructed. The UI is preview/review only and exposes loading, denied, expired, revoked,
stale, approval-required, approved/consumed, conflict, and safe-success states. Demo stays
deterministic and gains no hidden write capability, worker, queue, scheduler, provider, or automatic
effect.

## Exact Terra sequence

1. Persist immutable proposal records only when necessary, with narrow migration constraints.
2. Add only CSRF-protected server-owned proposal and approval APIs.
3. Test altered bindings, expiry/revocation/replay, cross-user/workspace denial, exact/conflicting
   duplicates, and stale revisions.
4. Stop. Do not perform a note write, rollback, worker, queue, scheduler, delegation, provider,
   visual redesign, Luna audit, or Milestone 4.4 work without new authorization.

## Validation status

- Added: pure reversible-write contract tests; focused contract/policy set passed (`23 passed`).
- Broader local checks: backend suite passed (`205 passed, 1 skipped`), strict mypy passed (`54`
  source files), new-file Ruff format/lint passed, hygiene and built-in secret scan passed (`230`
  source files), `git diff --check` passed, and focused prohibited-scope scan found no runtime
  keywords. Full backend lint retains only pre-existing untouched-file findings; documentation
  Prettier was unavailable locally and is not claimed as passed.
- Still required for Terra: persistence, migration, API/CSRF, transaction, scope, consumption,
  stale/concurrent state, audit/Trace, and idempotency tests.
- Required after a separately authorized effect: atomic mutation and rollback-conflict tests.
