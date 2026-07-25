# Milestone 4.4 Bounded Execution Reliability Completion

Status: complete locally; ready for a separately authorized combined Milestone 4 audit.

## Protected repository state

- Branch: `milestone-4.4-bounded-execution-reliability-local`
- Final-audit starting point: `8ab476d411f58639ea093662b5024d60c2e37752`
- Migration-validator correction: `787c80f` — `Fix Milestone 4.4 migration validation`
- Upstream: none
- Alembic sole head: `20260724_0015`
- `main`: `f04ace592e253c48172d129331ed8cd9bc4d4f4f`
- `competition-demo-v1`: `b45b7763b65861f9dfb3be7edf9b5eb271950917`
- Remote operations: none

All work and commits remained local under the remote freeze through August 13, 2026.

## Completed reliability architecture

Milestone 4.4 uses the existing controlled execution as its sole authority and adds no competing
execution framework. The database persists a server-owned deadline, attempt limit and count, lease
owner and expiry, monotonically advancing lease generation, retry eligibility, completion time,
terminal outcome, and safe failure classification.

Claims, renewals, releases, expired-lease recovery, retry execution, cancellation, deadline
termination, and result acceptance reload the owned execution and validate its current lifecycle
and authority. Guarded writes bind the current lifecycle state, lease owner, and lease generation.
Immutable database constraints protect execution identity and authority, bound attempts, enforce
the lease shape, and keep terminal state closed.

The retry vocabulary and timing are closed and deterministic. Only the fixed transient failure
classes are retryable; delays are deterministic exponential intervals capped at 60 seconds.
Neither attempts nor retry time can pass the immutable execution deadline.

Cancellation and deadline termination clear active ownership, advance the lease generation, close
the lifecycle, synchronize terminal metadata, and write audit plus Trace evidence atomically.
Result acceptance requires the exact live owner and generation, an unexpired lease, an open
deadline, and fresh grant and approval authority. This fences results from cancelled, expired,
recovered, superseded, or already completed deliveries.

There is no mutable consumed flag. Immutable request, transition, audit, Trace, effect, and
rollback-result records remain the evidence boundary. Duplicate delivery returns an existing
authoritative outcome or fails closed; it does not create another mutation or effect.

## Verified invariants

- One guarded claim can own an execution at a time.
- Every ownership change advances generation and fences earlier workers.
- Attempt count cannot exceed `max_attempts`.
- Recovery and retry fail closed at the deadline or when the next delay would cross it.
- Completed, failed, denied, exhausted, cancelled, and deadline-terminated executions do not
  reopen.
- Cancellation immediately invalidates the active lease.
- Deadline termination is idempotent and emits one terminal outcome.
- A stale worker cannot renew, release, publish a result, mutate a note, or persist an effect.
- Competing or duplicate deliveries create at most one authoritative mutation and effect.
- Expired, revoked, invalid, or cross-scope authority fails closed.
- API and browser input cannot supply lease, generation, deadline, attempt, retry, result,
  capability, grant, effect, or terminal authority.
- Audit and Trace evidence is rolled back when the surrounding transaction fails.

## Concurrency results

Deterministic SQLite coverage passed for competing lease claims, expired-lease recoveries, retry
deliveries, cancellations, terminal completion, stale generations after recovery, and results
arriving after cancellation, deadline termination, or another worker's success.

Each race produced one authoritative owner or terminal result. The other contender returned an
idempotent duplicate or safe closed conflict. The retry-delivery race produced one action call,
one attempt, and one terminal success. The cancellation race produced one cancellation transition,
one audit event, and one Trace event. SQLite lock contention is converted to a safe conflict and
does not expose SQL or database details.

These tests validate application invariants on SQLite. PostgreSQL runtime locking and concurrency
were not run and are not claimed.

## Failure-injection results

The affected suite passed injected failures at:

- claim audit/Trace persistence;
- action mutation before effect persistence;
- effect/result handling before lifecycle completion;
- retry scheduling Trace persistence;
- recovery Trace persistence;
- cancellation lease fencing;
- cancellation lifecycle transition;
- cancellation Trace persistence;
- deadline termination Trace persistence;
- rollback mutation, result, and audit persistence.

Every injected failure rolled back the surrounding unit: no partial note mutation, effect, result,
lease, generation, attempt, retry schedule, lifecycle transition, terminal metadata, audit event,
or Trace event remained. No failed transaction reported false success.

## Migration validation

Migration `20260724_0015` remains the sole head and no new migration was required.

The final audit corrected `scripts/validate_migrations.py` from obsolete `0012 -> 0011`
expectations to the authoritative `0015 -> 0014` cycle. A regression test now loads the Alembic
graph and requires the helper's expected head and prior revision to match the actual sole head and
its parent.

SQLite validation passed:

- clean database upgrade to `20260724_0015`;
- `20260724_0015 -> 20260724_0014 -> 20260724_0015`;
- the migration module's `0014 -> 0015 -> 0014 -> 0015` backfill and schema cycle;
- sole-head inspection;
- execution reliability columns, indexes, check constraints, and deterministic backfill.

The complete migration test module passed `11` tests.

## Validation results

| Check                                       | Result                         |
| ------------------------------------------- | ------------------------------ |
| Complete affected backend group             | `307 passed`                   |
| Complete migration module                   | `11 passed`                    |
| Standalone clean migration cycle            | Passed: `0015 -> 0014 -> 0015` |
| Focused changed-file Ruff format/lint       | Passed                         |
| Strict mypy, backend source                 | Passed: `60 source files`      |
| Strict mypy, changed validator/test files   | Passed: `2 source files`       |
| Python compilation and imports              | Passed                         |
| SQLAlchemy mapper validation                | Passed: `51` tables            |
| Alembic sole-head check                     | Passed: `20260724_0015`        |
| Repository hygiene and built-in secret scan | Passed: `253 source files`     |
| Git diff and whitespace checks              | Passed                         |
| Prohibited-scope scan                       | Passed                         |

The affected group covers reliability, recovery, retry, cancellation, deadlines, health,
concurrency, failure injection, lifecycle, persistence, capability and approval authority, scope,
idempotency, reversible writes and rollback, API authentication and CSRF, audit, Trace, and
migrations.

A repository-wide format/lint read-only check also reported pre-existing findings outside the
Milestone 4.4 final-audit diff:

- formatter: `20260724_0010_agent_prepared_execution.py` and `apps/api/scripts/demo.py`;
- Ruff: import ordering in migrations `0008` and `0010`, an overlong line in migration `0010`,
  and import ordering in `tests/postgres_support.py`.

They were not changed because this audit is scoped to confirmed Milestone 4.4 defects. Focused
format and lint for every changed file passed.

Frontend suites, network-dependent audits, and PostgreSQL runtime were not run, as required by the
audit scope.

## Defects corrected

1. The standalone migration validator expected obsolete head `20260724_0012` and parent
   `20260724_0011`. It now validates `20260724_0015` and `20260724_0014`.
2. The new graph regression prevents a future migration from silently leaving those expectations
   stale.
3. Strict typing of the touched migration test exposed a reused local name with incompatible
   dictionary/set types. The downgrade assertion now uses a precise `column_names` local.

No execution runtime, schema, transaction, authorization, concurrency, or data-integrity defect
was found by the final audit.

## Explicitly deferred and prohibited

Frontend cancellation controls remain deferred. This audit added no worker, queue, scheduler,
polling loop, autonomous execution, delegation, recursion, new capability, broader write
authority, provider, external call, competing execution framework, Milestone 5 behavior, or
combined Milestone 4 audit work.

## Handoff

Milestone 4.4 is complete locally. The next action is only a separately authorized combined
Milestone 4 audit. Do not begin Milestone 5 automatically.
