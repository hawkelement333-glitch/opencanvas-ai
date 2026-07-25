# Milestone 4.4 Recovery and Retry Execution Handoff

Status: checkpoint 2 complete locally; ready for separately authorized checkpoint 3.

## Repository state

- Branch: `milestone-4.4-bounded-execution-reliability-local`
- Authorized checkpoint-2 baseline: `5d5a7b83c901fb8955e2602682ebc99de60b18cf`
- Implementation commits:
  - `74a32bd` — `Add execution recovery and retry policy`
  - `af99981` — `Test retry duplicate effect safety`
  - `f062069` — `Test recovery and duplicate delivery`
- Upstream: none
- Alembic sole head: `20260724_0015`
- `main`: `f04ace592e253c48172d129331ed8cd9bc4d4f4f`
- `competition-demo-v1`: `b45b7763b65861f9dfb3be7edf9b5eb271950917`
- Remote operations: none

## Recovery contract

`ControlledExecutionReliability.recover_expired_lease` is the internal recovery boundary. Recovery
is permitted only when all of the following remain true:

- the user/workspace/execution scope resolves;
- the current lifecycle state is `running`;
- the persisted grant and required approval are still active and correctly bound;
- the supplied expected generation is the exact current generation;
- the current lease is expired;
- the deadline is still open;
- the attempt count is below the fixed maximum;
- the deterministic next retry fits before the deadline;
- no authoritative reversible-write effect already exists.

The guarded update clears the abandoned owner and timing, increments generation to fence the stale
owner, persists `next_retry_at`, and appends `ready` with safe reason `lease_expired`. The same
transaction writes `execution.lease_recovered` audit and Trace evidence. Recovery never invokes an
action or mutates workspace content.

Active leases, stale generations, terminal/deadline/attempt bounds, inactive authority, and existing
effects fail closed. A stale owner cannot renew or release after recovery because both lifecycle
state and generation no longer match.

## Retry policy

The retry policy is closed and server-owned:

- retryable: `provider_timeout`, `provider_unavailable`,
  `storage_temporarily_unavailable`;
- terminal: `authority_invalid`, `action_conflict`, `action_invalid`, `unsupported_action`;
- unknown exceptions: terminal `action_invalid`;
- delay: deterministic exponential 5, 10, 20, 40, then capped at 60 seconds;
- attempts: never exceed the immutable `max_attempts`;
- delay and eligibility: never pass the immutable deadline;
- no random jitter and no caller-supplied delay or classification.

Retryable failure with remaining time and attempts returns the execution to `ready`, clears the
lease, advances the fencing generation, persists the next retry time, and records
`execution.retry_scheduled`. A terminal class, exhausted attempt, or exhausted retry window appends
`failed`, clears lease/retry state through the existing terminal synchronizer, and records one
`execution.retry_failed`.

## Safe action execution and duplicate delivery

`execute_retry` is an internal trusted-adapter primitive. It:

1. returns an existing terminal success for duplicate delivery without claiming or executing;
2. atomically claims an eligible retry and increments the attempt count once;
3. runs the action in a nested savepoint;
4. rolls action mutations back before recording a retryable or terminal failure;
5. verifies the exact owner/generation before accepting an outcome;
6. appends the lifecycle result and audit/Trace evidence in the same outer transaction.

`execute_reversible_write_retry` is the closed note-write entry point. It accepts only owned scope,
execution identity, and server time. It reloads the persisted reversible proposal, derives the
idempotency key on the server, and invokes the existing Milestone 4.3
`ReversibleWriteEffectService`. It adds no mutation implementation or authority field.

A successful retry produces one immutable effect and one terminal success. Re-delivery returns the
existing terminal success and does not call the action again. SQLite concurrency coverage produced
one action call and one durable attempt under two competing deliveries.

## Atomicity evidence

Focused failure injection covers these rollback boundaries:

- an action mutation followed by a trusted transient failure is removed before retry scheduling;
- a Trace failure after a successful action removes the action mutation, claim, attempt, running
  transition, audit event, and terminal state;
- a Trace failure while scheduling a retry removes the claim, generation, attempt, schedule, and
  audit event;
- a Trace failure during expired-lease recovery restores the prior expired owner/generation and
  leaves no ready transition or retry time.

The real reversible-note integration proves the existing effect service is reused and duplicate
delivery produces one note and one effect.

## Validation

| Check                                                | Result                     |
| ---------------------------------------------------- | -------------------------- |
| Focused reliability plus reversible-effect modules   | `105 passed`               |
| Affected backend regression group                    | `265 passed`               |
| Focused Ruff format and lint                         | Passed                     |
| Full backend strict mypy                             | Passed, `60 source files`  |
| Python compilation/imports                           | Passed                     |
| SQLAlchemy mapper configuration                      | Passed, `51` tables        |
| Alembic sole head                                    | `20260724_0015`            |
| Repository hygiene / built-in secret scan            | Passed, `250` source files |
| Committed diff / whitespace / prohibited-scope scans | Passed                     |

The affected regression group covered reliability, lifecycle, persistence/schema, idempotency,
policy, API, contracts, reversible proposals/effects, Trace, and migrations on SQLite. PostgreSQL
runtime was not run or claimed.

The legacy standalone `scripts/validate_migrations.py` helper is still pinned to expected head
`20260724_0012`; it raises its pre-existing stale-head error after successfully applying migrations
through `20260724_0015`. The authoritative migration test module passed and `alembic heads` reports
the correct sole head. No migration changed in checkpoint 2.

## Prohibited-scope confirmation

Checkpoint 2 added no:

- cancellation or deadline-driven cancellation;
- cancellation-related late/stale result suppression;
- public retry or lease API;
- frontend behavior;
- worker, queue, scheduler, polling loop, or autonomous execution;
- delegation, recursion, or decision loop;
- capability, grant type, provider, embedding call, or external service;
- rollback redesign, Milestone 5, or later work.

The only lifecycle expansion is the explicit `running -> ready` transition required for persisted
bounded retry.

## Exact checkpoint-3 handoff

Checkpoint 3 must implement only authoritative cancellation and stale-result suppression. It should:

1. bind cancellation to the owned execution and current lifecycle state;
2. atomically terminalize cancellation and clear active lease/retry fields;
3. fence the current generation so late owners cannot accept or persist results;
4. reject late action, effect, lifecycle, audit, and Trace completion after cancellation;
5. preserve one safe cancellation outcome under duplicate/concurrent requests;
6. add focused transaction, stale-generation, concurrent cancellation, and no-partial-result tests.

Do not add frontend work, a worker, queue, scheduler, polling loop, autonomous behavior, a new
capability/provider, or the final checkpoint-4 audit while implementing checkpoint 3.
