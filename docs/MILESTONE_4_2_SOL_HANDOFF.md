# Milestone 4.2 Sol safety-core handoff

Status: **SOL SAFETY CORE COMPLETE — MILESTONE 4.2 NOT COMPLETE**

The repository contains the complete bounded Sol safety core through cancellation and late-result
suppression. Terra provider/API/UI implementation and Luna final validation were not started in
this recovery task and require separate authorization.

## Repository state

- Branch: `milestone-4-controlled-agents`.
- Recovery starting local and remote SHA:
  `9bb70e41269465daff314d7a27c43ec6ca1bb0ed`.
- Lifecycle checkpoint: `18b995e` (`Enforce controlled execution lifecycle`).
- Immutable-context checkpoint: `6cde6f6` (`Resolve immutable controlled-agent context`).
- Cancellation/result checkpoint: `87dd85a` (`Reject stale controlled-agent results`).
- The final documentation commit follows this handoff; resolve it after commit.
- Protected tag object: `acbde89b6e2cc3e41c372887794726d393836716`.
- Protected tag peeled commit: `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

## Completed Sol boundary

### Closed authority and execution identity

- The only action remains `generate_grounded_draft`.
- The action registry is closed to selected reads, internal draft creation, citation validation, and
  scoped Trace reads. Workspace mutation, external effects, and delegation remain prohibited.
- Server-authenticated user/workspace/canvas scope, stored grant/approval records, canonical
  context/plan digests, one-time approval consumption, and database request idempotency are
  verified before execution authority exists.
- Exact redelivery reuses the stored request identity. Conflicting idempotency-key reuse fails
  closed and appends bounded audit evidence.

### Lifecycle safety

- Migration `20260723_0009` adds append-only transition guards.
- Executions must begin in `proposed`; only closed successors are accepted.
- `succeeded`, `failed`, `cancelled`, and `denied` are terminal and cannot reopen.
- Unique execution/sequence and execution/predecessor constraints provide database compare-and-set
  protection against two authoritative successors from one prior state.
- Current state is selected by validated transition sequence, not caller-controlled timestamps.

### Immutable selected context

- The resolver reloads the stored append-only context and verifies user, workspace, execution,
  canvas, snapshot identity, and canonical digest.
- Selected canvas/node/document-version/chunk resources are resolved through ownership-scoped
  exact-version queries. Missing versions, deletion, changed revisions, altered content hashes,
  unsupported kinds, duplicate selections, and cross-scope references fail closed.
- Every selected resource and the complete ordered context package receive domain-separated
  canonical digests.
- Content remains explicitly untrusted evidence. Embedded instructions cannot change authority,
  scope, lifecycle, tools, or policy.
- Later workspace changes cannot mutate a context package already resolved at the approved boundary.

### Cancellation and result acceptance

- Cancellation is authoritative and idempotent before or during execution.
- Cancellation after a different terminal outcome is rejected without changing that outcome.
- Supersession is represented by authoritative cancellation with a replacement execution identity;
  the superseded execution cannot publish a result.
- Result acceptance binds the authenticated user, execution/workspace, exact running-state ID,
  stored context snapshot/digest, immutable resolution digest, and result digest.
- Acceptance rechecks the consumed approval/policy binding, grant and approval activity, and grant
  revocation at publication time.
- Cancelled, stale, superseded, expired, revoked, altered, or terminal execution results are
  rejected and recorded without becoming authoritative.
- Exact duplicate result delivery is idempotent. Conflicting reuse of a delivery identity fails
  closed.

## Final Sol validation

- Initial reconstructed focused baseline: `53 passed`.
- Lifecycle/persistence/schema/API/migration checkpoint: `28 passed`.
- Immutable-context/contract/authority checkpoint: `19 passed`.
- Cancellation/lifecycle/context checkpoint: `14 passed`.
- Complete final Sol contract, policy, persistence, authority, idempotency, lifecycle, immutable
  context, cancellation/result, and migration gate: `74 passed`.
- Migration validation: upgrade `20260723_0009`, downgrade `20260721_0008`, re-upgrade
  `20260723_0009` passed.
- Ruff format check: `19 files already formatted`.
- Ruff lint: passed.
- Mypy: passed for all six controlled-agent source modules/model target.
- Repository hygiene and built-in secret scan: passed for `216` source files.
- High-confidence secret scan: no matches.
- `git diff --check`: passed.
- Dependency audit: no package or lock file changed.
- PostgreSQL: **NOT RUN**. Docker is unavailable and
  `OPENCANVAS_POSTGRES_TEST_URL` is not configured; the marked PostgreSQL test reported one skip.

## Security and concurrency conclusion

- Missing, unknown, mismatched, expired, revoked, replayed, altered, or cross-scope authority fails
  closed.
- Approval consumption and request idempotency remain database-backed.
- Lifecycle terminality and successor exclusivity are database-backed.
- Cancellation/result orderings are directly tested without timing delays:
  cancel-before-start, start/cancel/result, start/result/cancel, revoke/result, expire/result,
  supersede/result, stale-state/result, duplicate result, conflicting redelivery, and duplicate
  cancellation.
- Rejected late results preserve safe audit evidence and cannot overwrite terminal outcomes.
- Authoritative PostgreSQL trigger and concurrent transition execution remain unverified until a
  PostgreSQL-capable environment runs the marked suite.

## Exact Terra handoff — remaining implementation only

Terra may begin only after separately authorized and must preserve the Sol contracts:

1. Connect the authorized immutable context package to the existing explicitly configured reasoning
   provider abstraction. Production must never fall back to deterministic/mock behavior.
2. Add bounded grounded draft generation with existing request, context, output, token, cost, and
   provider limits.
3. Validate claims and citations server-side against the exact resolved source versions/passages.
4. Preserve supported, conflict, unsupported, and insufficient-evidence behavior.
5. Persist provider metadata, usage, safe failures, complete Trace evidence, exact context identity,
   citations, and result-publication decisions.
6. Add only narrow authenticated start and cancel API routes for one owned canvas and selected
   context.
7. Add the smallest read-only execution UI required by Milestone 4.2.
8. Add provider-failure, prompt-injection, budget, cancellation, two-user/workspace-isolation,
   citation, insufficient-evidence, Trace, API, and UI tests.

Terra must not add durable workspace writes, tools/effects, a worker, queue, scheduler, delegation,
recursive agents, autonomous initiation, or Milestone 4.3 behavior.

## Exact Luna handoff — remaining validation only

After Terra is complete and separately handed off, Luna should:

1. Verify every Milestone 4.2 exit criterion against code and tests.
2. Run the full approved backend, integration, security, migration, demo, deterministic replay,
   frontend, type, lint, formatting, hygiene, secret, and production-build gates.
3. Run the PostgreSQL marked suite in a configured PostgreSQL-capable environment or record the
   exact unresolved limitation without claiming a pass.
4. Confirm two-user/workspace isolation, provider failure, prompt injection, budgets, cancellation,
   citation validation, insufficient evidence, Trace completeness, and production refusal of mock
   fallback.
5. Fix only confirmed Milestone 4.2 defects, finish the completion report, commit, normally push,
   and stop before Milestone 4.3.

Luna must not redesign the implementation, import Milestone 3.75, or add later-milestone features.

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
