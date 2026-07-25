# Milestone 4.4 Cancellation and Stale-Result Suppression Handoff

Status: checkpoint 3 complete locally; ready for a separately authorized final reliability audit.

## Repository state

- Branch: `milestone-4.4-bounded-execution-reliability-local`
- Authorized checkpoint-3 baseline: `0a610a54565664674c8d12e76385b8b74df08349`
- Implementation commit: `8d03d8e` — `Add controlled execution cancellation and fencing`
- Upstream: none
- Alembic sole head: `20260724_0015`
- `main`: `f04ace592e253c48172d129331ed8cd9bc4d4f4f`
- `competition-demo-v1`: `b45b7763b65861f9dfb3be7edf9b5eb271950917`
- Remote operations: none

## Cancellation model

The existing controlled-execution cancellation endpoint remains the only public cancellation
surface. It is authenticated, CSRF-protected, ownership-scoped, and accepts only an idempotency key.
The server derives the cancellation identity, user, workspace, execution, time, lifecycle outcome,
lease fencing, and terminal metadata.

Cancellation is permitted for nonterminal proposed, approval-waiting, ready, retry-waiting, and
running executions. For an active lease, the service atomically:

1. verifies the owned execution and current nonterminal lifecycle;
2. clears active ownership and retry eligibility;
3. advances lease generation to fence the current worker;
4. appends the existing `cancelled` terminal lifecycle state;
5. synchronizes completion, terminal outcome, and safe failure classification;
6. writes one `execution.cancelled` audit event;
7. writes one `execution.cancelled` Trace event.

These operations share one nested transaction. The service is cooperative: it invalidates the
worker’s authority to publish but does not claim to terminate an operating-system process.

Exact idempotency replay returns the prior outcome. A later cancellation of an already-cancelled
execution returns the existing terminal result without another transition, audit event, or Trace
event. Successful, failed, denied, and exhausted executions are never reopened.

Cross-user and cross-workspace requests fail closed. Canvas, outcome, deadline, attempt, retry,
lease, capability, grant, effect, and result override fields are rejected by the allowlist API
schema.

## Deadline enforcement

`ControlledExecutionReliability.terminate_expired` is the internal server deadline boundary.

- Before the immutable deadline, it returns unchanged.
- At or after the deadline, it atomically fences generation, clears lease/retry state, appends
  `cancelled` with `execution_deadline_exceeded`, and records audit plus Trace evidence.
- Repeated evaluation returns the same terminal deadline outcome without duplicate evidence.
- Existing terminal success/failure/denial remains unchanged.
- Claim, renewal, recovery, retry, and result acceptance all reject an expired execution.
- No API or request can extend or replace `deadline_at`.

No migration was required; migration `20260724_0015` already represents all necessary invariants.

## Stale-worker and stale-result guarantees

A controlled grounded draft now enters `running` through the checkpoint-1 atomic claim service and
retains its server-generated lease identity only inside the service process. Result acceptance
requires, in the same transaction:

- the current `running` lifecycle state and state identity;
- exact active lease owner;
- exact lease generation;
- unexpired lease;
- open server deadline;
- nonterminal execution;
- matching user/workspace/execution/context identity;
- still-active and correctly bound grant and approval authority.

Consequently:

- a worker finishing after cancellation is rejected;
- a worker finishing after deadline termination is rejected;
- an older generation finishing after expired-lease recovery is rejected;
- a second delivery after terminal success is rejected without reopening;
- expired or revoked authority cancels/fences the execution before rejection;
- stale workers cannot renew or release a newer lease;
- rejected results create no successful lifecycle state, accepted-result audit, or success Trace.

The checkpoint-2 retry transaction still verifies current owner/generation before accepting action
success. Reversible-note retries reuse `ReversibleWriteEffectService`; cancellation or deadline
before retry prevents both note mutation and immutable effect persistence.

## Derived operational health

Execution inspection now contains a safe derived health object:

- `waiting_claimable`
- `actively_leased`
- `waiting_retry`
- `cancelled`
- `deadline_exceeded`
- `completed`
- `failed`
- `exhausted`
- `inconsistent`

It includes lifecycle status, claimable/terminal/lease-active booleans, attempt count and limit,
deadline, optional retry time, and safe reason code. It omits lease owner identity, worker secrets,
grant/approval details beyond the existing allowlisted inspection contract, raw policy payloads,
SQL, stack traces, and exception text.

`inconsistent` is fail-closed for combinations such as `running` without an active lease, `ready`
with an owner, or lifecycle/terminal metadata disagreement.

## Atomicity and failure injection

Focused failure injection proves:

- failure after lease fencing restores the original owner, generation, and running state;
- failure after the cancellation transition restores the lease and removes terminal metadata;
- cancellation Trace failure removes the transition, terminal metadata, audit event, and fence;
- deadline Trace failure restores the active lease and leaves the execution nonterminal;
- checkpoint-2 action/result failure tests continue to protect mutation, effect, lifecycle, retry,
  audit, and Trace atomicity.

No injected failure leaves false cancellation/deadline evidence or an incorrectly advanced
generation.

## Concurrency

The deterministic file-backed SQLite cancellation race test ran three consecutive times. Two
simultaneous requests yielded:

- one durable `cancelled` terminal outcome;
- one duplicate or safe closed conflict;
- exactly one cancellation audit event;
- exactly one cancellation Trace event.

SQLite lock contention is converted to the safe `cancellation_conflict` API result rather than
leaking SQL or database details. PostgreSQL runtime concurrency was not run or claimed.

The checkpoint-2 competing retry-delivery test remains the authoritative terminal-completion race
coverage: one action, one attempt, one terminal success.

## Validation

| Check                                                | Result                     |
| ---------------------------------------------------- | -------------------------- |
| Directly affected modules                            | `134 passed`               |
| Broader affected backend regression group            | `303 passed`               |
| Focused Ruff format and lint                         | Passed                     |
| Full backend strict mypy                             | Passed, `60 source files`  |
| Python compilation/imports                           | Passed                     |
| SQLAlchemy mapper configuration                      | Passed, `51` tables        |
| Alembic sole head                                    | `20260724_0015`            |
| Repository hygiene / built-in secret scan            | Passed, `251` source files |
| Committed diff / whitespace / prohibited-scope scans | Passed                     |

The broader group covered cancellation, deadline, reliability, grounded draft, authority,
immutable context, lifecycle, persistence/schema, idempotency, policy, API, contracts, reversible
writes/effects, Trace, and migrations on SQLite.

No frontend, network-dependent, PostgreSQL runtime, or unrelated repository-wide test was run or
claimed.

## Defects corrected

- Active cancellation previously cleared lease fields through terminal synchronization without
  advancing generation. It now explicitly fences the generation.
- Lifecycle cancellation/result audit evidence previously had no paired Trace event. It now does.
- Grounded result publication previously relied on running-state identity but not lease identity,
  expiration, generation, or the server deadline. All are now required.
- Simultaneous SQLite cancellation could expose `database is locked`. It now returns a safe
  conflict.
- Formatting the touched grounded-draft module exposed broad `object` annotations whose line-level
  ignores no longer applied. `_request_from_inspection` now uses the existing concrete
  `AgentInspection` type and passes strict mypy without suppression.

## Prohibited-scope confirmation

Checkpoint 3 added no:

- frontend cancellation control;
- worker, queue, scheduler, polling loop, or autonomous behavior;
- recurring execution, delegation, recursion, or decision loop;
- capability, provider, embedding call, external service, or broader write authority;
- rollback redesign, final Milestone 4.4 audit, combined Milestone 4 audit, or Milestone 5 work.

The legacy standalone migration helper pinned to `20260724_0012` remains documented and unchanged.

## Exact final-audit handoff

The next checkpoint must be only the separately authorized final Milestone 4.4 reliability audit.
It should reconcile checkpoints 1–3, run the complete required affected gate once, verify local
demo safety where applicable, and update final completion documentation. It must not add frontend
features, new runtime behavior, later milestones, or remote operations.
