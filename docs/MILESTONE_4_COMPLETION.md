# Milestone 4 Combined Completion

Status: complete locally; ready for Milestone 5 architecture only.

Audit date: 2026-07-25 (America/Chicago)

## Protected repository state

- Audit baseline: `0e9a2d23325f59a1044a32a79e38d6b7282de01c`.
- Branch: `milestone-4.4-bounded-execution-reliability-local`.
- Upstream: none.
- Alembic sole head: `20260724_0015`.
- Protected `main`: `f04ace592e253c48172d129331ed8cd9bc4d4f4f`.
- Protected `competition-demo-v1` tag object:
  `acbde89b6e2cc3e41c372887794726d393836716`.
- Protected `competition-demo-v1` tagged commit:
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- No push, pull, fetch, sync, upstream, pull request, remote branch/tag change, publication, upload,
  deployment, release, or other remote operation occurred.

The remote freeze through August 13, 2026 remained in force throughout the audit.

## Closed Milestone 4 system

### 4.1 deny-by-default policy and authority contracts

Closed capabilities, immutable ownership and scope, canonical plan/context/grant/approval digests,
fixed validity windows, revocations, replay checks, and deterministic policy evaluation deny
missing, expired, revoked, altered, replayed, or cross-scope authority.

### 4.1B append-only persistence boundary

Execution identities, transitions, snapshots, grants, revocations, approvals, consumptions, policy
decisions, and audit evidence are append-only. Composite ownership constraints and database
triggers protect the boundary. Approval consumption revalidates stored canonical evidence and is
atomic and single-use.

### 4.2 user-started selected-context read-only grounded agent

The authenticated user explicitly prepares and starts an execution over one owned canvas and exact
selected node IDs. The server reloads immutable context, performs grounded generation, validates
citations against eligible sources, persists evidence and Trace, and returns a read-only result.
Cancellation and late-result suppression remain server-authoritative.

### 4.3 approved reversible writes and rollback

The only write effects are explicitly approved note creation and exact-revision note update. Each
effect is atomic, idempotent, and paired with immutable evidence. Create rollback removes only the
created note. Update rollback restores the exact prior title and text. Rollback review, approval,
execution, and replay protection remain distinct and scope-bound.

### 4.4 bounded execution reliability

Claims, leases, monotonically increasing generations, deadlines, attempt bounds, deterministic
retry, recovery, cancellation, terminal outcomes, and result acceptance share one authoritative
execution lifecycle. A recovered, cancelled, deadline-expired, superseded, or stale worker cannot
commit a result or effect.

## Required scenario evidence

| Required scenario                                         | Combined-audit evidence                                                                                                                                                                                                |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Selected-context read-only execution with exact citations | Backend grounded-draft tests passed. Chromium now submits the exact selected UUID list to prepare/run, displays the result without adding a canvas node, opens Citation [1], and verifies the exact persisted passage. |
| Approved note creation and update execute once            | `test_approved_creation_is_atomic_idempotent_and_traced`, `test_approved_update_uses_exact_revision_and_preserves_before_after_evidence`, and duplicate-effect tests passed.                                           |
| Exact duplicate delivery does not repeat mutations        | Request idempotency, effect duplicate, rollback duplicate, retry duplicate, and result-delivery duplicate tests passed with one authoritative effect/result.                                                           |
| Create rollback removes only the created note             | The create case of `test_approved_rollback_executes_atomically_and_is_exactly_idempotent` passed and verifies authoritative absence for that note.                                                                     |
| Update rollback restores exact prior title and text       | The update case of the same test passed and verifies `("Before", "Before text")` plus the expected revision.                                                                                                           |
| Bounded retry succeeds once                               | `test_bounded_retry_succeeds_on_next_eligible_attempt`, duplicate retry delivery, and competing retry delivery tests passed.                                                                                           |
| Recovered stale worker cannot commit                      | Lease-generation and recovered-worker stale-result tests passed.                                                                                                                                                       |
| Cancelled/deadline-expired worker cannot commit           | Cancellation, deadline termination, late provider result, and result-acceptance fencing tests passed.                                                                                                                  |
| Invalid authority fails closed                            | Expired, revoked, altered, missing, replayed, wrong-user, wrong-workspace, wrong-resource, and cross-scope policy/persistence/execution tests passed.                                                                  |
| Failed transactions leave no partial state                | Failure injection passed across mutation, effect/result, lease, attempt, retry schedule, lifecycle, terminal metadata, audit, and Trace boundaries.                                                                    |

## Exact validation results

| Validation                                  | Result                                                                                                |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Combined focused Milestone 4 backend group  | `307 passed, 1 skipped` across 23 files                                                               |
| Complete backend suite                      | `412 passed, 1 skipped`                                                                               |
| Security-marked backend suite               | `28 passed`                                                                                           |
| Optional PostgreSQL-marked suite            | `1 skipped`; no dedicated safe PostgreSQL test URL was configured                                     |
| Complete frontend unit/component suite      | `48 passed` across 11 files                                                                           |
| Chromium browser smoke                      | `2 passed, 2 skipped`; synthetic current-UI workflows passed, PostgreSQL-gated real workflows skipped |
| Production Next.js build                    | Passed; compilation, TypeScript, page generation, and optimization completed                          |
| Frontend TypeScript and ESLint              | Passed                                                                                                |
| Backend strict mypy                         | Passed for 60 source files                                                                            |
| Repository-wide Prettier                    | Passed                                                                                                |
| Repository-wide Ruff format                 | Passed for 130 Python files                                                                           |
| Repository-wide Ruff lint                   | Passed                                                                                                |
| Standalone migration cycle                  | Passed: `0015 -> 0014 -> 0015`                                                                        |
| Alembic graph                               | Sole head `20260724_0015`                                                                             |
| Complete migration module                   | `11 passed` within both green backend groups                                                          |
| Python compilation and imports              | Passed                                                                                                |
| SQLAlchemy mapper validation                | Passed for 51 tables                                                                                  |
| Deterministic demo reset/check/smoke        | Passed; replay mode, external AI disabled, API ready, web ready                                       |
| Repository hygiene and built-in secret scan | Passed for 254 source files                                                                           |
| Dependency manifest/lock diff               | Passed; no dependency change                                                                          |
| Git whitespace/diff check                   | Passed                                                                                                |
| Prohibited production-scope scan            | Passed; no Milestone 5 behavior or new production runtime scope                                       |

The desktop pnpm fallback wrapper attempted its own dependency-policy install and stopped before
project validation because native build scripts were already ignored. No dependency or policy
configuration was changed. Every project check represented by the aggregate pipeline was executed
directly through the repository-pinned Corepack/local binaries and passed as recorded above.

SQLite provides the deterministic local concurrency and migration evidence. PostgreSQL runtime
locking, trigger execution, and concurrency were not run and are not claimed because this host did
not provide `OPENCANVAS_POSTGRES_TEST_URL`.

## Concrete defects fixed

1. Browser smoke tests still targeted the obsolete mutable assistant-result canvas flow and old
   visual labels. They now exercise the current controlled prepare/run contract with valid UUIDs,
   exact selected context, read-only results, exact citation passage navigation, insufficient
   evidence, and no result-node mutation.
2. The combined repository-wide style gate exposed previously documented formatting/import debt.
   Configured formatters corrected import ordering, one migration statement width, and frontend
   test indentation. No runtime behavior or schema semantics changed.

No controlled-agent runtime, authority, transaction, rollback, concurrency, cancellation,
deadline, retry, recovery, or stale-result defect was found.

## Recorded future roadmap — not implemented

5. Living Knowledge Graph and AI Workflows
6. Multi-Workspace Collaboration
   - Nested and Federated Mobius Workspaces
7. Production Hardening
8. Public Portfolio and Product Release
9. SolarPlexus Agent Ecosystem

This audit stops before Milestone 5 implementation.
