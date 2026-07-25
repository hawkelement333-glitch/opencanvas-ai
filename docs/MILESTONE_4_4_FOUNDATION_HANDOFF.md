# Milestone 4.4 Execution Ownership Foundation Handoff

Status: checkpoint 1 complete locally; Milestone 4.4 is not complete.

## Repository state

- Authorized baseline: `57488d77573a0f099384de6fd12d02de2827d33d`
- Branch: `milestone-4.4-bounded-execution-reliability-local`
- Upstream: none
- Implementation commits:
  - `c24fee7` — `Add durable execution reliability contracts`
  - `a999856` — `Add atomic execution lease ownership`
  - `623faf0` — `Enforce authority on lease renewal`
- Alembic sole head: `20260724_0015`
- `main`: `f04ace592e253c48172d129331ed8cd9bc4d4f4f`
- `competition-demo-v1`: `b45b7763b65861f9dfb3be7edf9b5eb271950917`
- Remote operations: none

## Completed checkpoint scope

The existing `controlled_agent_executions` row remains the sole execution identity and now carries
server-owned reliability state:

- fixed deadline;
- positive maximum-attempt limit;
- bounded current attempt count;
- optional next retry eligibility;
- opaque server-generated lease owner;
- lease acquisition and expiration;
- monotonic lease generation;
- final completion timestamp;
- closed terminal outcome and safe failure classification.

Default policy for newly persisted executions is:

- deadline: creation plus 15 minutes;
- maximum attempts: 3;
- current attempts: 0;
- lease generation: 0;
- no retry eligibility or active lease.

No request or browser contract accepts these values.

## Ownership and lifecycle contract

`ControlledExecutionReliability` is an internal service using guarded database updates rather than
an in-process lock.

### Claim

- Requires the owned execution to be in the existing `ready` state.
- Revalidates stored grant/approval scope, bindings, expiry, and revocation.
- Rejects terminal, deadline-expired, attempt-exhausted, retry-ineligible, and actively leased rows.
- Atomically generates the owner identity, increments generation and attempt count, assigns bounded
  lease timing, transitions through the existing lifecycle registry to `running`, and writes safe
  audit and Trace evidence.

### Renewal

- Requires `running`, the exact current owner, exact generation, and an unexpired lease.
- Revalidates authority at renewal time.
- Caps expiration at the immutable execution deadline.
- Writes safe audit and Trace evidence without exposing the owner token.

### Release

- Requires `running`, the exact current owner and generation, and an unexpired lease.
- Clears only active ownership timing and identity.
- Preserves attempt count, generation, lifecycle history, audit, and Trace history.

### Terminal synchronization

The existing terminal transitions (`succeeded`, `failed`, `cancelled`, and `denied`) now close the
reliability fields in the same transaction. They set completion/outcome/classification, clear lease
and retry state, and remain closed under the existing append-only transition rules.

## Persistence and migration

Migration `20260724_0015_execution_reliability.py`:

- adds the reliability columns to the existing execution table;
- backfills existing deadlines deterministically from `created_at + 15 minutes`;
- enforces deadline, attempt, retry, lease-shape, generation, completion, outcome, and failure
  classification constraints;
- adds claimability and lease-expiration indexes;
- supports SQLite and PostgreSQL schema semantics;
- upgrades, downgrades, and re-upgrades on SQLite.

Milestone 4.1 made the complete execution row append-only. Migration `0015` narrows only that row's
update guard: identity, ownership scope, schema, role, context, plan, grant, and creation time remain
immutable at both ORM and database boundaries; deletion remains prohibited. Only the declared
server-owned reliability fields can change.

## Validation

| Check                                                               | Result                   |
| ------------------------------------------------------------------- | ------------------------ |
| Focused execution reliability tests                                 | 27 passed                |
| Lifecycle, persistence, schema, and complete migration module       | 30 passed                |
| Affected controlled-agent and Trace regression group                | 257 passed               |
| SQLite `0014 -> 0015 -> 0014 -> 0015` cycle and backfill            | Passed                   |
| Focused Ruff format and lint                                        | Passed                   |
| Strict mypy                                                         | Passed, 60 source files  |
| Python compilation/imports and SQLAlchemy mapper validation         | Passed                   |
| Alembic sole-head check                                             | `20260724_0015`          |
| Repository hygiene                                                  | Passed, 249 source files |
| Diff, whitespace, secret-like-material, and prohibited-scope checks | Passed                   |

The deterministic file-backed SQLite contention test produced exactly one owner and one safe
conflict. This validates the local guarded-update behavior only; PostgreSQL runtime locking was not
run or claimed.

Injected Trace failure rolled back the lease assignment, attempt increment, `running` transition,
controlled-agent audit event, and Trace event together.

## Defects corrected during checkpoint 1

- The original blanket append-only execution trigger blocked legitimate reliability updates and
  migration backfill. It is now a narrow immutable-authority guard, with deletion still blocked.
- SQLite returns timezone-naive persisted datetimes; service-side comparisons normalize them to UTC.
- Simultaneous SQLite writes can report a database lock. The internal service converts that specific
  contention into a safe closed claim conflict without exposing SQL or database detail.
- Renewal initially checked lease identity but not fresh grant revocation/expiry. Renewal now repeats
  the same stored-authority validation and has a regression test.

## Explicitly deferred

Checkpoint 2 must implement only:

- expired-lease takeover for a previously running execution;
- crash recovery;
- persisted retry eligibility and bounded retry execution;
- duplicate-result suppression needed by retry delivery.

Checkpoint 3 remains responsible for:

- deadline-driven cancellation;
- stale worker fencing beyond lease ownership;
- late/stale result suppression and health states.

Checkpoint 4 remains the final Milestone 4.4 reliability audit.

No recovery runner, retry loop, worker, queue, scheduler, cancellation change, stale-result behavior,
frontend, public reliability API, capability, write authority, provider, autonomous execution, or
later milestone was added in checkpoint 1.

## Exact continuation

Start from the clean local handoff commit on
`milestone-4.4-bounded-execution-reliability-local`. Read this document and
`docs/MILESTONE_4_PROGRESS.md`, then design the smallest server-authoritative expired-lease takeover
and retry state transition atop migration `0015`. Preserve the existing authority revalidation,
lease generation fencing, audit/Trace transaction, and attempt/deadline bounds. Stop before
cancellation, stale-result suppression, frontend work, or the final Milestone 4.4 audit.
