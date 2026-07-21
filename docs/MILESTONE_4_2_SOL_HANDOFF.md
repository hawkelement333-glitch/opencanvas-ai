# Milestone 4.2 Sol safety-core handoff

Status: **partial recovery handoff after checkpoint 1**. The Sol safety core is not complete and the
Terra continuation must not begin yet.

## Repository state

- Starting branch: `milestone-4-controlled-agents`.
- Starting local and remote SHA: `3ab717199470da6b82b36da559c1ccc5a84e8c29`.
- Implemented checkpoint: `daaa5106582929fd05d7f884eb11f9f31b801327`.
- Protected tag object: `acbde89b6e2cc3e41c372887794726d393836716`.
- Protected tag peeled commit: `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

## Architecture decisions completed

- The only action is `generate_grounded_draft`.
- The closed action registry allows only selected canvas/context/document/retrieval reads, an
  internal draft result, and scoped Trace reads. Maximum risk is `r1_draft`; workspace mutation,
  external effects, and delegation are false.
- The strict internal request binds server-resolved user, workspace, canvas, immutable context and
  plan references/digests, stored grant/approval references, idempotency key, optional client
  request ID, and correlation ID. Extra fields—including raw client authority—are rejected.
- The immutable plan contains exactly six ordered stages: validate authority, load immutable
  context, retrieve selected evidence, generate grounded draft, validate citations, and
  record/return. No dynamic steps, tools, delegation, recursion, or effects are possible.
- Canonical idempotency identity binds user, workspace, canvas, action, key, context/plan identity
  and digests, and grant/approval identity. Transport request/correlation IDs are excluded.

## Existing foundation inspected

Milestone 4.1B already loads stored execution, context, plan, grant, approval, revocations, and
prior consumptions; recomputes stored contract digests; invokes the pure deny-by-default evaluator;
and atomically records an allow decision with one approval consumption in a nested transaction.
Ownership reads require the execution user, active owned workspace, and execution ID. This must be
reused rather than replaced.

## Focused validation

- Contract tests: `6 passed`.
- Changed-file Ruff format: passed.
- Changed-file Ruff lint: passed.
- Focused mypy: passed for two files.
- `git diff --check`: passed.
- Repository hygiene and built-in secret scan: passed for `208` source files.
- PostgreSQL: **NOT RUN**. No migration changed.

Full backend, security, demo, PostgreSQL, frontend, production build, provider, and deployment
checks were not run for this narrow checkpoint.

## Incomplete Sol work

- Trusted preflight orchestration and closed-action-to-capability enforcement
- Database-enforced idempotency and parallel-request behavior
- Append-only transition validation and terminal-state rules
- Immutable selected-node/document-version/chunk context resolution
- Prompt-injection isolation tests for the resolved context package
- Cancellation and late-result publication guards
- Complete authority, ownership, replay, no-effects, and concurrency tests

No provider call, citation generation, Trace completion, public execution/cancel API, UI, migration,
workspace effect, tool, worker, queue, scheduler, delegation, or child execution was added.

## Exact next Sol continuation order

1. Add a trusted internal preflight service that verifies the request references against stored
   execution/context/plan/grant/approval records and reuses `consume_approval`.
2. Add the smallest database-enforced idempotency design, in a separate migration checkpoint if
   required, with identical-retry and conflicting/parallel-reuse tests.
3. Add append-only transition validation without adding a succeeded state to the provider-free path.
4. Resolve the exact selected immutable context without current-version substitution or broad search.
5. Add cancellation and late-result suppression guards.
6. Run the complete focused Sol security gate and update this document from partial to complete.

Only after all six Sol steps pass may Terra proceed in this order:

1. Connect the authorized context package to the existing reasoning-provider abstraction.
2. Add bounded grounded generation.
3. Add server-side claim and citation validation.
4. Add insufficient-evidence handling.
5. Add Trace, usage, and safe error completion records.
6. Add the narrow start and cancel API routes.
7. Add the smallest read-only UI.
8. Expand tests.
9. Run complete Milestone 4.2 validation.

## Resume commands

```powershell
cd C:\Users\hawke\Documents\Codex\2026-07-18\referenced-chatgpt-conversation-this-is-untrusted\work\opencanvas-ai
git branch --show-current
git status --short
git fetch origin
git rev-parse HEAD
git rev-parse origin/milestone-4-controlled-agents
git show-ref --tags -d competition-demo-v1
Get-Content docs/MILESTONE_4_PROGRESS.md
Get-Content docs/MILESTONE_4_2_SOL_HANDOFF.md
```
